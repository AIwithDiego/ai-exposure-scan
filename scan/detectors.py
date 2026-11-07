"""Detectors: plain-code checks over out/raw/*.json. No model, no network.

Findings use method "detected", except hosting behind a CDN ("judged": the CDN's address may not be the real
server). Keys are masked in every string a finding carries.
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from scan import geo
from scan.score import compute_score, merge_findings

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SNIPPET_MAX = 200
KEY_CONTEXT = 30  # chars each side of a key -> ~60 chars around the match

COUNTRY_NAMES = {
    "US": "the US", "CA": "Canada", "GB": "the UK", "FR": "France", "DE": "Germany",
    "PL": "Poland", "ES": "Spain", "IE": "Ireland", "NL": "the Netherlands",
    "AT": "Austria", "BE": "Belgium", "BG": "Bulgaria", "HR": "Croatia", "CY": "Cyprus",
    "CZ": "Czechia", "DK": "Denmark", "EE": "Estonia", "FI": "Finland", "GR": "Greece",
    "HU": "Hungary", "IT": "Italy", "LV": "Latvia", "LT": "Lithuania", "LU": "Luxembourg",
    "MT": "Malta", "PT": "Portugal", "RO": "Romania", "SK": "Slovakia", "SI": "Slovenia",
    "SE": "Sweden", "CH": "Switzerland", "NO": "Norway", "IS": "Iceland", "AU": "Australia",
    "NZ": "New Zealand", "SG": "Singapore", "JP": "Japan", "IN": "India", "CN": "China",
    "HK": "Hong Kong", "IL": "Israel", "BR": "Brazil", "ZA": "South Africa", "KR": "South Korea",
}
EU_COUNTRIES = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE",
    "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
}
CDNS = [  # (name, header, substring in its value or None for "header present")
    ("Cloudflare", "cf-ray", None),
    ("Cloudflare", "server", "cloudflare"),
    ("Vercel", "x-vercel-id", None),
    ("CloudFront", "x-amz-cf-id", None),
    ("Fastly", "x-served-by", None),
]


def _load(name):
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


VENDORS = _load("chatbot-vendors.json")["vendors"]
KEY_PATTERNS = [
    {**p, "compiled": re.compile(p["regex"])} for p in _load("key-patterns.json")["patterns"]
]
CRAWLERS = _load("ai-crawlers.json")["crawlers"]
SERVICES = _load("services.json")["services"]


# ---------- helpers ----------

def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def short_name(name):
    """'OpenAI API (called from the browser)' -> 'OpenAI API'."""
    return name.split(" (")[0]


def mask_key(key):
    return key[:8] + "…" + key[-4:]


def key_spans(text):
    """Sorted (start, end, pattern) for every key in text; earlier patterns win overlaps."""
    taken = []
    for p in KEY_PATTERNS:
        for m in p["compiled"].finditer(text):
            s, e = m.span()
            if not any(s < te and ts < e for ts, te, _ in taken):
                taken.append((s, e, p))
    return sorted(taken, key=lambda t: t[0])


def mask_text(text):
    """Mask every key in the whole text. Returns (masked, spans, to_masked), where spans are
    key_spans(text) and to_masked(i, end=False) maps an index in text to one in masked."""
    spans = key_spans(text)
    parts, moved, pos, mpos = [], [], 0, 0
    for s, e, _ in spans:
        masked = mask_key(text[s:e])
        parts += [text[pos:s], masked]
        mpos += s - pos
        moved.append((s, e, mpos, mpos + len(masked)))
        mpos += len(masked)
        pos = e
    parts.append(text[pos:])

    def to_masked(i, end=False):
        delta = 0
        for s, e, ms, me in moved:
            if i <= s:
                break
            if i < e:
                return me if end else ms
            delta = me - e
        return i + delta

    return "".join(parts), spans, to_masked


def mask_all_keys(text):
    """Mask every key-like string in text."""
    return mask_text(text)[0]


def clip(text, limit=SNIPPET_MAX):
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def line_around(text, start, end, limit=SNIPPET_MAX):
    """The line containing text[start:end], trimmed to limit chars centred on the match.
    Keys are masked in the whole text before the window is cut."""
    text, _, to_masked = mask_text(text)
    start, end = to_masked(start), to_masked(end, end=True)
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    if line_end == -1:
        line_end = len(text)
    if line_end - line_start > limit:
        half = (limit - (end - start)) // 2
        line_start = max(line_start, start - max(half, 0))
        line_end = min(line_end, line_start + limit)
    return clip(text[line_start:line_end], limit)


TWO_PART_SUFFIXES = {"co", "com", "org", "net", "ac", "gov", "edu"}


def registrable_domain(host):
    """Heuristic registrable domain: 'www.shop.example.co.uk' -> 'example.co.uk', 'js.hs-scripts.com' ->
    'hs-scripts.com'. IP addresses and single-label hosts like 'localhost' come back as they are."""
    host = (host or "").lower().strip().strip("[]").rstrip(".")
    if ":" in host or host.replace(".", "").isdigit():
        return host
    labels = [x for x in host.split(".") if x]
    if len(labels) >= 3 and labels[-2] in TWO_PART_SUFFIXES and len(labels[-1]) == 2:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def country_name(code):
    return COUNTRY_NAMES.get(code, code)


def page_url(raw):
    return raw.get("final_url") or raw.get("url") or raw["site"]


def origin(raw):
    m = re.match(r"^(https?://[^/]+)", page_url(raw))
    return m.group(1) if m else page_url(raw).rstrip("/")


def finding(raw, type_, slug, title, severity, where, snippet, fix, meta=None, method="detected"):
    f = {
        "id": f"{raw['site']}:{type_}:{slug}",
        "type": type_,
        "title": title,
        "severity": severity,
        "method": method,
        "evidence": {"where": mask_all_keys(where), "snippet": clip(mask_all_keys(snippet or ""))},
        "fix": fix,
    }
    if meta:
        f["meta"] = {k: mask_all_keys(v) if isinstance(v, str) else v for k, v in meta.items()}
    return f


# ---------- checks ----------

def _host_path(url):
    parts = urlsplit(url)
    return parts.netloc + parts.path


def _vendor_hit(raw, vendor):
    """First (where, snippet) where any of the vendor's match strings appears, else None."""
    matches = vendor["match"]
    for s in raw.get("scripts") or []:
        src = s.get("src")
        if src and any(m in _host_path(src) for m in matches):
            return src, f'<script src="{src}">'
    for r in raw.get("requests") or []:
        url = r.get("url") or ""
        domain = r.get("domain") or ""
        if any(m in domain or m in _host_path(url) for m in matches):
            return url, f"{r.get('method', 'GET')} {url}"
    for s in raw.get("scripts") or []:
        content = s.get("content")
        if s.get("inline") and content:
            for m in matches:
                i = content.find(m)
                if i != -1:
                    return page_url(raw), line_around(content, i, i + len(m))
    return None


def chatbots(raw):
    """One info finding per chatbot / AI vendor found in script srcs, requests or inline scripts."""
    findings = []
    for vendor in VENDORS:
        hit = _vendor_hit(raw, vendor)
        if not hit:
            continue
        where, snippet = hit
        name = short_name(vendor["name"])
        is_api = "(called from the browser)" in vendor["name"]
        if is_api:
            provider = name.removesuffix(" API")
            title = f"Your site sends requests to {provider} from visitors' browsers"
            fix = (f"Your pages send requests to {provider}'s AI service from each visitor's browser, "
                   "which can expose your account details. Ask your web person to send these requests "
                   f"through your own server instead, and to name {provider} in your privacy policy.")
        else:
            title = f"{name} chat widget on the homepage"
            fix = (f"Your site has a chat window from {name}. That's fine; "
                   "just make sure it's named in your privacy policy.")
        meta = {"vendor": name, "country": vendor["country"], "eu": vendor["eu"]}
        findings.append(finding(raw, "chatbot", slugify(name), title, "info", where, snippet, fix, meta))
    return findings


def data_transfer(raw, vendors_found):
    """One low finding per found vendor based outside the EU. vendors_found: chatbot findings."""
    by_name = {short_name(v["name"]): v for v in VENDORS}
    findings = []
    for cf in vendors_found:
        vendor = by_name.get(cf["meta"]["vendor"])
        if not vendor or vendor["eu"]:
            continue
        name = short_name(vendor["name"])
        country = COUNTRY_NAMES.get(vendor["country"], vendor["country"])
        is_api = "(called from the browser)" in vendor["name"]
        what = "Visitor data" if is_api else "Chat messages"
        title = f"{what} likely go to {country} ({name})"
        fix = f"{name} is a company based in {country}, so this data is likely stored outside the EU. "
        if vendor["eu_option"]:
            fix += f"Ask your web person whether {name}'s EU data hosting is switched on."
        else:
            fix += f"Ask your web person to name {name} in your privacy policy, or consider an EU-based tool."
        meta = {"vendor": name, "country": vendor["country"], "eu": False, "eu_option": vendor["eu_option"]}
        findings.append(finding(raw, "data_transfer", slugify(name), title, "low",
                                cf["evidence"]["where"], cf["evidence"]["snippet"], fix, meta))
    return findings


def _cdn(headers):
    headers = {k.lower(): str(v) for k, v in (headers or {}).items()}
    for name, header, needle in CDNS:
        value = headers.get(header)
        if value is not None and (needle is None or needle in value.lower()):
            return name
    return None


def hosting(raw):
    """Where the main page was served from: server IP -> country (DB-IP), CDN from response headers.
    No finding when the IP is unknown, private or not in the database."""
    ip = raw.get("server_ip")
    code = geo.country_of(ip) if ip else None
    if not code:
        return []
    cdn = _cdn(raw.get("server_headers"))
    country = country_name(code)
    in_eu = code in EU_COUNTRIES
    if cdn:
        title = f"Your site is served through {cdn} from {country}"
        fix = (f"Your site is delivered through {cdn}, a network that answers visitors from a city near them, "
               "so the server we reached can differ from where your site really lives. "
               "Ask your web person where your main server is and that your privacy policy names your host.")
    elif in_eu:
        title = f"Your site is hosted in {country}"
        fix = f"Your website's server is in {country}, inside the EU. Nothing to do."
    else:
        title = f"Your site is hosted in {country}"
        fix = (f"Your website's server appears to be in {country}, outside the EU, so visitor data likely "
               "leaves the EU. Ask your web person whether your host offers EU hosting, and to name it in "
               "your privacy policy.")
    headers = raw.get("server_headers") or {}
    snippet = " · ".join([f"server address {ip} ({code})"] + [f"{k}: {v}" for k, v in headers.items()])
    meta = {"kind": "hosting", "ip_country": code, "cdn": cdn}
    return [finding(raw, "data_transfer", "hosting", title, "info" if in_eu else "low", page_url(raw),
                    snippet, fix, meta, method="judged" if cdn else "detected")]


def _matches_domain(host, domain):
    return host == domain or host.endswith("." + domain)


def _service_match(host, path, m):
    domain, _, prefix = m.partition("/")
    return _matches_domain(host, domain) and (not prefix or path.startswith("/" + prefix))


def _service_for(host, path=""):
    """First services.json entry matching host (and path, for "domain/path" match strings)."""
    return next((s for s in SERVICES if any(_service_match(host, path, m) for m in s["match"])), None)


SHARED_DOMAINS = {"googleapis.com", "gstatic.com", "amazonaws.com", "cloudfront.net"}


def _is_vendor_host(host, vendors):
    """True if host belongs to one of the given chatbot vendors: a domain-like match string matches it,
    or it shares a (not shared-infrastructure) registrable domain with one."""
    reg = registrable_domain(host)
    for v in vendors:
        for m in v["match"]:
            m = m.split("/")[0].lower()
            if "." not in m or not re.fullmatch(r"[a-z0-9.-]+", m):
                continue
            if _matches_domain(host, m) or (reg == registrable_domain(m) and reg not in SHARED_DOMAINS):
                return True
    return False


def _contacted(raw):
    """(host, path) pairs the page contacted (requests and script src URLs), in first-seen order.
    A script tag that was never fetched (e.g. held back by a consent banner) doesn't count."""
    pairs = []
    requested = set()
    for r in raw.get("requests") or []:
        parts = urlsplit(r.get("url") or "")
        pairs.append((r.get("domain") or parts.hostname or "", parts.path))
        requested.add(r.get("url"))
    for s in raw.get("scripts") or []:
        if s.get("src") and (s.get("content") is not None or s["src"] in requested):
            parts = urlsplit(s["src"])
            pairs.append((parts.hostname or "", parts.path))
    seen = []
    for h, path in pairs:
        pair = (h.lower().strip("[]").rstrip("."), path or "/")
        if pair[0] and pair not in seen:
            seen.append(pair)
    return seen


def services(raw, vendors_found):
    """One aggregated finding for the other outside services the page contacts (data/services.json).
    Skips the site's own domain and the chat / AI vendors already reported. vendors_found: chatbot findings."""
    own = registrable_domain(urlsplit(page_url(raw)).hostname or raw["site"].split(":")[0])
    found_names = {cf["meta"]["vendor"] for cf in vendors_found}
    found_vendors = [v for v in VENDORS if short_name(v["name"]) in found_names]
    found, domains, unknown = {}, [], []
    for host, path in _contacted(raw):
        if registrable_domain(host) == own or _is_vendor_host(host, found_vendors):
            continue
        svc = _service_for(host, path)
        if svc:
            found.setdefault(svc["name"], svc)
            if host not in domains:
                domains.append(host)
        elif not _is_vendor_host(host, VENDORS):
            reg = registrable_domain(host)
            if reg not in unknown:
                unknown.append(reg)
    if not found and not unknown:
        title = "No other outside services on your homepage" if vendors_found else \
            "Your homepage doesn't contact any outside services"
        fix = ("Nothing to do. If you add analytics, fonts, videos or maps later, "
               "name them in your privacy policy and your cookie banner.")
        meta = {"kind": "services", "services": [], "outside_eu_count": 0, "unknown_domains": []}
        return [finding(raw, "data_transfer", "services", title, "info", page_url(raw),
                        f"Only {own} was contacted while the homepage loaded", fix, meta)]
    listed = [{"name": s["name"], "country": s["country"], "eu": s["eu"], "category": s["category"]}
              for s in found.values()]
    outside = sum(1 for s in listed if not s["eu"])
    n = len(listed)
    if n:
        noun = "service" if n == 1 else "services"
        tail = f"{outside} likely outside the EU" if outside else "all likely inside the EU"
        title = f"Your site sends visitor data to {n} outside {noun}, {tail}"
    else:
        title = f"Your site contacts {len(unknown)} other {'website' if len(unknown) == 1 else 'websites'} while loading"
    fix = ("Each visitor's browser contacts these companies when your homepage loads. "
           "Check these are all in your privacy policy and your cookie banner asks before loading them.")
    shown = (domains + unknown)[:6]
    snippet = ", ".join(shown) + (" …" if len(domains) + len(unknown) > len(shown) else "")
    meta = {"kind": "services", "services": listed, "outside_eu_count": outside, "unknown_domains": unknown[:10]}
    return [finding(raw, "data_transfer", "services", title, "low" if outside else "info", page_url(raw),
                    snippet, fix, meta)]


def _key_sources(raw):
    for s in raw.get("scripts") or []:
        if s.get("content"):
            yield (s.get("src") or "inline script"), s["content"]
    if raw.get("html"):
        yield page_url(raw), raw["html"]


def key_leaks(raw):
    """One finding per distinct key. Only masked forms ever leave this function."""
    findings = []
    seen = set()
    for where, text in _key_sources(raw):
        masked, spans, to_masked = mask_text(text)
        for start, end, p in spans:
            digest = hashlib.sha256(text[start:end].encode()).hexdigest()[:10]
            if digest in seen:
                continue
            seen.add(digest)
            mstart, mend = to_masked(start), to_masked(end, end=True)
            snippet = masked[max(0, mstart - KEY_CONTEXT):mend + KEY_CONTEXT]
            findings.append(_key_finding(raw, p, digest, where, snippet))
    return findings


def _key_finding(raw, pattern, digest, where, snippet):
    key_type = short_name(pattern["key_type"])
    if pattern["severity"] == "high":
        title = f"Secret {key_type} key visible in your site's code"
        fix = (f"This key works like a password for your {key_type} account, and anyone who views your "
               "site's code can copy it and run up charges. Ask your web person to cancel it in your "
               f"{key_type} account and keep the replacement on your server, out of the page.")
    else:
        title = f"{key_type} key in your site's code (probably a public Maps key)"
        fix = (f"This looks like a {key_type} key, usually for Maps, which is meant to be public. "
               "Nothing urgent: ask your web person to check it only works on your website.")
    return finding(raw, "key_leak", f"{slugify(key_type)}-{digest}", title, pattern["severity"],
                   where, snippet, fix, {"key_type": key_type})


def parse_robots(text):
    """Return list of (agents, rules, lines) groups from a robots.txt."""
    groups = []
    agents, rules, lines = [], [], []
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        field, value = (x.strip() for x in line.split(":", 1))
        field = field.lower()
        if field == "user-agent":
            if rules:
                groups.append((agents, rules, lines))
                agents, rules, lines = [], [], []
            agents.append(value)
            lines.append(line)
        elif field in ("allow", "disallow") and agents:
            rules.append((field, value))
            lines.append(line)
    if agents:
        groups.append((agents, rules, lines))
    return groups


def _crawler_rules(raw):
    where = origin(raw) + "/robots.txt"
    robots = raw.get("robots_txt")
    fix_none = ("Optional: a robots.txt file tells bots which pages they may read, including AI companies' bots. "
                "Ask your web person if you'd like to allow or block them.")
    if robots is None:
        return finding(raw, "agent_ready", "crawler-rules", "No rules for AI bots (no robots.txt file)", "info",
                       where, "robots.txt not found", fix_none, {"blocked": [], "allowed": [], "not_mentioned": [c["agent"] for c in CRAWLERS]})
    groups = parse_robots(robots)
    blocked, allowed, not_mentioned, used = [], [], [], []
    for c in CRAWLERS:
        idxs = [i for i, g in enumerate(groups) if any(a.lower() == c["agent"].lower() for a in g[0])]
        if not idxs:
            not_mentioned.append(c["agent"])
            continue
        rules = [r for i in idxs for r in groups[i][1]]
        if ("disallow", "/") in rules and ("allow", "/") not in rules:
            blocked.append(c["agent"])
        else:
            allowed.append(c["agent"])
        used.extend(i for i in idxs if i not in used)
    lines = [ln for i in sorted(used) for ln in groups[i][2]]
    meta = {"blocked": blocked, "allowed": allowed, "not_mentioned": not_mentioned}
    if not blocked and not allowed:
        return finding(raw, "agent_ready", "crawler-rules", "No rules for AI bots in robots.txt", "info",
                       where, robots[:SNIPPET_MAX].strip() or "robots.txt is empty", fix_none, meta)
    parts = []
    if blocked:
        parts.append(f"blocks {', '.join(blocked)}")
    if allowed:
        parts.append(f"allows {', '.join(allowed)}")
    title = clip(f"Your robots.txt {' and '.join(parts)}", 70)
    fix = ("Your robots.txt file tells some AI companies' bots whether they may read your site. "
           "Others aren't mentioned, so they follow your general rules. "
           "Ask your web person to review the list if that's not what you want.") if not_mentioned else \
          "Your robots.txt file has rules for every AI bot we know of. Nothing to do."
    return finding(raw, "agent_ready", "crawler-rules", title, "info", where, " | ".join(lines), fix, meta)


MCP_URL = re.compile(r"""https?://[^\s"'<>()]*\bmcp\b[^\s"'<>()]*""", re.IGNORECASE)
MCP_NAMED = re.compile(r"\bmcp\s+(?:server|endpoint)s?\b", re.IGNORECASE)
MCP_NEAR = 60  # chars between "MCP server" and its URL
HTTP_URL = re.compile(r"""https?://[^\s"'<>()]+""")


def _mcp(raw):
    """An MCP endpoint the site itself names: an http(s) URL with 'mcp' in it, or
    'MCP server/endpoint' with a URL close by on the same line. Never requests anything."""
    sources = [
        (origin(raw) + "/llms.txt", raw.get("llms_txt")),
        (page_url(raw), raw.get("page_text")),
        (page_url(raw), raw.get("html")),
    ]
    for where, text in sources:
        if not text:
            continue
        hit = MCP_URL.search(text)
        if hit:
            url, start, end = hit.group(0), hit.start(), hit.end()
        else:
            url = None
            for m in MCP_NAMED.finditer(text):
                ls = max(text.rfind("\n", 0, m.start()) + 1, m.start() - MCP_NEAR)
                le = text.find("\n", m.end())
                le = min(le if le != -1 else len(text), m.end() + MCP_NEAR)
                line_url = HTTP_URL.search(text, ls, le)
                if line_url:
                    url, start, end = line_url.group(0), m.start(), m.end()
                    break
        if url:
            return finding(raw, "agent_ready", "mcp", "Your site offers AI assistants a way to connect (MCP)", "info",
                           where, line_around(text, start, end),
                           "AI assistants can use this connection to look up or do things with your business. "
                           "Ask your web person to make sure it only shares what you're happy to share.",
                           {"mcp_url": url})
    return None


def agent_ready(raw):
    findings = []
    llms_where = origin(raw) + "/llms.txt"
    llms = raw.get("llms_txt")
    if llms is None:
        findings.append(finding(raw, "agent_ready", "no-llms-txt", "No llms.txt guide for AI assistants", "info", llms_where,
                                "llms.txt not found",
                                "Optional: an llms.txt file tells AI assistants what your business is about. "
                                "Your web person can add one in a few minutes."))
    else:
        first = next((ln for ln in llms.splitlines() if ln.strip()), "llms.txt is empty")
        findings.append(finding(raw, "agent_ready", "has-llms-txt", "Has an llms.txt guide for AI assistants", "info", llms_where, first,
                                "Your llms.txt file tells AI assistants what your business is about. "
                                "Ask your web person to keep it up to date."))
    findings.append(_crawler_rules(raw))
    mcp = _mcp(raw)
    if mcp:
        findings.append(mcp)
    return findings


# ---------- pipeline ----------

def detect(raw):
    """All detector findings for one raw site dict."""
    if raw.get("error"):
        return []
    bots = chatbots(raw)
    return bots + data_transfer(raw, bots) + hosting(raw) + services(raw, bots) + key_leaks(raw) + agent_ready(raw)


def site_entry(raw, findings):
    entry = {
        "site": raw["site"],
        "final_url": raw.get("final_url"),
        "status": raw.get("status"),
        "error": raw.get("error"),
        "score": compute_score(findings, raw.get("error")),
        "findings": findings,
    }
    if raw.get("label"):
        entry = {"site": entry.pop("site"), "label": mask_all_keys(raw["label"]), **entry}
    return entry


def run(raw_dir, findings_path):
    """Read every raw file, write findings.json. Keeps non-detector findings already in findings.json."""
    raw_dir, findings_path = Path(raw_dir), Path(findings_path)
    existing = {}
    if findings_path.exists():
        try:
            old = json.loads(findings_path.read_text(encoding="utf-8"))
            existing = {s["site"]: s.get("findings", []) for s in old.get("sites", [])}
        except (json.JSONDecodeError, KeyError, TypeError):
            existing = {}

    sites = []
    for path in sorted(raw_dir.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        kept = [] if raw.get("error") else [f for f in existing.get(raw["site"], [])
                                            if f.get("method") != "detected" and f.get("type") != "data_transfer"]
        findings = merge_findings(kept, detect(raw))
        entry = site_entry(raw, findings)
        sites.append(entry)
        counts = {}
        for f in findings:
            counts[f["type"]] = counts.get(f["type"], 0) + 1
        shown = "-" if entry["score"] is None else entry["score"]
        print(f"{raw['site']}  score {shown}  " + "  ".join(f"{k}: {v}" for k, v in counts.items()), flush=True)

    out = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "sites": sites}
    findings_path.parent.mkdir(parents=True, exist_ok=True)
    findings_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return out
