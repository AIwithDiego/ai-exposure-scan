"""Detectors: plain-code checks over out/raw/*.json. No model, no network.

Every finding uses method "detected". Keys are masked in every string a finding carries.
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from scan.score import compute_score, merge_findings

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SNIPPET_MAX = 200
KEY_CONTEXT = 30  # chars each side of a key -> ~60 chars around the match

COUNTRY_NAMES = {
    "US": "the US", "CA": "Canada", "GB": "the UK", "FR": "France", "DE": "Germany",
    "PL": "Poland", "ES": "Spain", "IE": "Ireland", "NL": "the Netherlands",
}


def _load(name):
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


VENDORS = _load("chatbot-vendors.json")["vendors"]
KEY_PATTERNS = [
    {**p, "compiled": re.compile(p["regex"])} for p in _load("key-patterns.json")["patterns"]
]
CRAWLERS = _load("ai-crawlers.json")["crawlers"]


# ---------- helpers ----------

def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def short_name(name):
    """'OpenAI API (called from the browser)' -> 'OpenAI API'."""
    return name.split(" (")[0]


def mask_key(key):
    return key[:8] + "…" + key[-4:]


def mask_all_keys(text):
    """Mask every key-like string in text."""
    for p in KEY_PATTERNS:
        text = p["compiled"].sub(lambda m: mask_key(m.group(0)), text)
    return text


def clip(text, limit=SNIPPET_MAX):
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def line_around(text, start, end, limit=SNIPPET_MAX):
    """The line containing text[start:end], trimmed to limit chars centred on the match."""
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    if line_end == -1:
        line_end = len(text)
    if line_end - line_start > limit:
        half = (limit - (end - start)) // 2
        line_start = max(line_start, start - max(half, 0))
        line_end = min(line_end, line_start + limit)
    return clip(mask_all_keys(text[line_start:line_end]), limit)


def page_url(raw):
    return raw.get("final_url") or raw.get("url") or raw["site"]


def origin(raw):
    m = re.match(r"^(https?://[^/]+)", page_url(raw))
    return m.group(1) if m else page_url(raw).rstrip("/")


def finding(raw, type_, slug, title, severity, where, snippet, fix, meta=None):
    f = {
        "id": f"{raw['site']}:{type_}:{slug}",
        "type": type_,
        "title": title,
        "severity": severity,
        "method": "detected",
        "evidence": {"where": mask_all_keys(where), "snippet": clip(mask_all_keys(snippet or ""))},
        "fix": fix,
    }
    if meta:
        f["meta"] = {k: mask_all_keys(v) if isinstance(v, str) else v for k, v in meta.items()}
    return f


# ---------- checks ----------

def _vendor_hit(raw, vendor):
    """First (where, snippet) where any of the vendor's match strings appears, else None."""
    matches = vendor["match"]
    for s in raw.get("scripts") or []:
        src = s.get("src")
        if src and any(m in src for m in matches):
            return src, f'<script src="{src}">'
    for r in raw.get("requests") or []:
        url = r.get("url") or ""
        domain = r.get("domain") or ""
        if any(m in domain or m in url for m in matches):
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
            title = f"Your site calls the {name} from the browser"
            fix = (f"Your site talks to the {name} directly from visitors' browsers. "
                   "Ask your web person to move AI calls to the server and to list the provider in your privacy policy.")
        else:
            title = f"{name} chat widget on the homepage"
            fix = (f"Your site has a {name} chat window. That's fine; "
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
        fix = f"{name} is based in {country}, so this data likely leaves the EU. "
        if vendor["eu_option"]:
            fix += f"Ask your web person whether {name}'s EU data hosting is switched on."
        else:
            fix += f"Ask your web person to name {name} in your privacy policy, or consider an EU-based tool."
        meta = {"vendor": name, "country": vendor["country"], "eu": False, "eu_option": vendor["eu_option"]}
        findings.append(finding(raw, "data_transfer", slugify(name), title, "low",
                                cf["evidence"]["where"], cf["evidence"]["snippet"], fix, meta))
    return findings


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
        taken = []  # spans already claimed by an earlier (more specific) pattern
        for p in KEY_PATTERNS:
            for m in p["compiled"].finditer(text):
                start, end = m.span()
                if any(start < e and s < end for s, e in taken):
                    continue
                taken.append((start, end))
                digest = hashlib.sha256(m.group(0).encode()).hexdigest()[:10]
                if digest in seen:
                    continue
                seen.add(digest)
                lo, hi = max(0, start - KEY_CONTEXT), min(len(text), end + KEY_CONTEXT)
                snippet = text[lo:start] + mask_key(m.group(0)) + text[end:hi]
                findings.append(_key_finding(raw, p, digest, where, snippet))
    return findings


def _key_finding(raw, pattern, digest, where, snippet):
    key_type = short_name(pattern["key_type"])
    if pattern["severity"] == "high":
        title = f"Secret {key_type} key visible in your site's code"
        fix = (f"A secret {key_type} key is visible to anyone who opens your site's code. "
               f"Ask your web person to delete this key in {key_type} today and move AI calls to the server.")
    else:
        title = f"{key_type} key visible in your site's code (likely Maps)"
        fix = (f"This looks like a {key_type} key, usually a Maps key that is meant to be public. "
               "Ask your web person to check it is restricted to your website.")
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
    fix_none = ("Optional: your robots.txt can say which AI companies may read your site. "
                "Ask your web person if you'd like to allow or block them.")
    if robots is None:
        return finding(raw, "agent_ready", "crawler-rules", "No robots.txt, so no AI crawler rules", "info",
                       where, "robots.txt not found", fix_none, {"blocked": [], "allowed": [], "not_mentioned": [c["agent"] for c in CRAWLERS]})
    groups = parse_robots(robots)
    blocked, allowed, not_mentioned, used = [], [], [], []
    for c in CRAWLERS:
        idx = next((i for i, g in enumerate(groups) if any(a.lower() == c["agent"].lower() for a in g[0])), None)
        if idx is None:
            not_mentioned.append(c["agent"])
            continue
        if ("disallow", "/") in groups[idx][1]:
            blocked.append(c["agent"])
        else:
            allowed.append(c["agent"])
        if idx not in used:
            used.append(idx)
    lines = [ln for i in sorted(used) for ln in groups[i][2]]
    meta = {"blocked": blocked, "allowed": allowed, "not_mentioned": not_mentioned}
    if not blocked and not allowed:
        return finding(raw, "agent_ready", "crawler-rules", "No AI crawler rules in robots.txt", "info",
                       where, robots[:SNIPPET_MAX], fix_none, meta)
    parts = []
    if blocked:
        parts.append(f"blocks {', '.join(blocked)}")
    if allowed:
        parts.append(f"allows {', '.join(allowed)}")
    title = clip(f"robots.txt {' and '.join(parts)}", 70)
    fix = ("Your robots.txt has rules for some AI crawlers. Others are not mentioned, so they follow your general rules. "
           "Ask your web person to review the list if that's not what you want.") if not_mentioned else \
          "Your robots.txt has rules for every known AI crawler. Nothing to do."
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
            return finding(raw, "agent_ready", "mcp", "Your site names an MCP server for AI agents", "info",
                           where, line_around(text, start, end),
                           "AI assistants can use this to work with your business. "
                           "Ask your web person to make sure it only shares what you're happy to share.",
                           {"mcp_url": url})
    return None


def agent_ready(raw):
    findings = []
    llms_where = origin(raw) + "/llms.txt"
    llms = raw.get("llms_txt")
    if llms is None:
        findings.append(finding(raw, "agent_ready", "no-llms-txt", "No llms.txt", "info", llms_where,
                                "llms.txt not found",
                                "Optional: an llms.txt file tells AI assistants what your business is about. "
                                "Your web person can add one in a few minutes."))
    else:
        first = next((ln for ln in llms.splitlines() if ln.strip()), "")
        findings.append(finding(raw, "agent_ready", "has-llms-txt", "Has llms.txt", "info", llms_where, first,
                                "Your llms.txt tells AI assistants what your business is about. "
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
    return bots + data_transfer(raw, bots) + key_leaks(raw) + agent_ready(raw)


def site_entry(raw, findings):
    return {
        "site": raw["site"],
        "final_url": raw.get("final_url"),
        "status": raw.get("status"),
        "error": raw.get("error"),
        "score": compute_score(findings, raw.get("error")),
        "findings": findings,
    }


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
        kept = [f for f in existing.get(raw["site"], []) if f.get("method") != "detected"]
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
