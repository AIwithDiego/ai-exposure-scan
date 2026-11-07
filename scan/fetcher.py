"""Fetcher: one passive page load per site, plus robots.txt, llms.txt and the linked privacy policy.

Writes out/raw/<site>.json in the format of docs/contract.md section 1.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
VIEWPORT = {"width": 1280, "height": 800}
GOTO_TIMEOUT_MS = 30_000
IDLE_TIMEOUT_MS = 10_000
SMALL_FETCH_TIMEOUT_MS = 10_000

HTML_CAP = 2 * 1024 * 1024
SCRIPT_CAP = 2 * 1024 * 1024
TEXT_CAP = 200 * 1024

SERVER_HEADERS = ["server", "via", "cf-ray", "x-vercel-id", "x-amz-cf-id", "x-served-by", "x-cache"]

PRIVACY_WORDS = ["privacy", "privacidad", "datenschutz", "confidentialit"]

FIND_PRIVACY_LINK_JS = """
({words, siteDomain}) => {
  const here = location.href.split('#')[0];
  const consentBanner = '[id*="cookiebot" i], [class*="cookiebot" i], [id*="cybotcookiebot" i], '
    + '[class*="cybotcookiebot" i], [id*="onetrust" i], [class*="onetrust" i], [id*="cookie-consent" i], '
    + '[class*="cookie-consent" i], [id*="cmp" i], [class*="cmp" i]';
  const vendorInfo = /more about (this|the) provider/i;
  const sameSite = (url) => {
    let host;
    try { host = new URL(url).hostname.toLowerCase().replace(/^\\[|\\]$/g, '').replace(/^www\\./, ''); } catch (e) { return false; }
    return host === siteDomain || host.endsWith('.' + siteDomain);
  };
  for (const a of document.querySelectorAll('a[href]')) {
    const rawText = a.innerText || a.textContent || '';
    const text = rawText.toLowerCase();
    const href = (a.getAttribute('href') || '').toLowerCase();
    if (!words.some(w => text.includes(w) || href.includes(w))) continue;
    if (!a.href.startsWith('http') || !sameSite(a.href)) continue;
    if (a.closest(consentBanner) || vendorInfo.test(rawText)) continue;
    const [target, hash = ''] = a.href.split('#');
    const samePageAnchor = target === here && !hash.startsWith('/') && !hash.startsWith('!');
    if (!samePageAnchor) return a.href;
  }
  return null;
}
"""

GENERIC_SECOND_LEVEL = {"co", "com", "org", "net", "ac", "gov"}


def _registrable(host):
    """Heuristic registrable domain: 'www.shop.example.co.uk' -> 'example.co.uk', 'www.zexel.io' -> 'zexel.io'."""
    host = (host or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if host.replace(".", "").isdigit():
        return host
    labels = host.split(".")
    if len(labels) >= 3 and labels[-2] in GENERIC_SECOND_LEVEL:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


COLLECT_SCRIPTS_JS = """
() => Array.from(document.querySelectorAll('script')).map(s => ({
  src: s.src || null,
  content: s.src ? null : (s.textContent || '')
}))
"""


LABEL_SEP = re.compile(r"\s+\|")  # " | name"; a | inside a URL (no space before it) stays part of the URL


def read_site_entries(path):
    """Read one domain or URL per line, optionally followed by " | display name", skipping blanks
    and # comments. Returns (url, label) pairs; label is None when not given."""
    entries = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = LABEL_SEP.split(line, maxsplit=1)
        line, label = parts[0].strip(), (parts[1].strip() if len(parts) > 1 else "")
        if not line.startswith(("http://", "https://")):
            line = "https://" + line
        parts = urlsplit(line)
        if parts.path == "":
            line = urlunsplit(parts._replace(path="/"))
        entries.append((line, label or None))
    return entries


def read_sites(path):
    """URLs from read_site_entries, without labels."""
    return [url for url, _ in read_site_entries(path)]


def site_name(url):
    """Bare host (with port if any), e.g. 'example.ie' or 'localhost:8765'."""
    return urlsplit(url).netloc.lower()


def raw_filename(site):
    return site.replace(":", "_") + ".json"


def _cap(text, limit):
    if text is None:
        return None
    if len(text.encode("utf-8")) <= limit:
        return text
    return text.encode("utf-8")[:limit].decode("utf-8", errors="ignore")


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def empty_raw(url, label=None):
    raw = {
        "site": site_name(url),
        "url": url,
        "final_url": None,
        "fetched_at": _now(),
        "status": None,
        "error": None,
        "html": None,
        "page_text": None,
        "scripts": [],
        "requests": [],
        "robots_txt": None,
        "llms_txt": None,
        "privacy_policy": None,
        "server_ip": None,
        "server_headers": {},
    }
    if label:
        raw["label"] = label
    return raw


def _looks_like_html(content_type, body):
    if "html" in (content_type or "").lower():
        return True
    head = body.lstrip()[:100].lower()
    return head.startswith("<!doctype html") or head.startswith("<html")


def _get_text_file(context, origin, path):
    """GET a small text file on the site's origin. Body if 200 and not HTML, else None."""
    try:
        resp = context.request.get(origin + path, timeout=SMALL_FETCH_TIMEOUT_MS, max_redirects=5)
    except PlaywrightError:
        return None
    try:
        if resp.status != 200:
            return None
        body = resp.body().decode("utf-8", errors="replace")
        if _looks_like_html(resp.headers.get("content-type"), body):
            return None
        return _cap(body, TEXT_CAP)
    except PlaywrightError:
        return None
    finally:
        resp.dispose()


def _fetch_privacy(context, url):
    page = context.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=GOTO_TIMEOUT_MS)
        try:
            page.wait_for_load_state("networkidle", timeout=IDLE_TIMEOUT_MS)
        except PlaywrightTimeout:
            pass
        text = page.evaluate("() => document.body ? document.body.innerText : ''")
        return {"url": page.url, "text": _cap(text, TEXT_CAP)}
    except PlaywrightError:
        return None
    finally:
        page.close()


def fetch_site(browser, url, label=None):
    """Visit one site passively and return its raw dict. Never raises."""
    raw = empty_raw(url, label)
    context = browser.new_context(user_agent=USER_AGENT, viewport=VIEWPORT, ignore_https_errors=True)
    try:
        page = context.new_page()
        script_responses = []

        def on_request(req):
            raw["requests"].append({
                "url": req.url,
                "domain": urlsplit(req.url).hostname or "",
                "method": req.method,
                "resource_type": req.resource_type,
            })

        def on_response(resp):
            if resp.request.resource_type == "script":
                script_responses.append(resp)

        page.on("request", on_request)
        page.on("response", on_response)

        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=GOTO_TIMEOUT_MS)
            raw["status"] = response.status if response else None
            raw["server_ip"] = _server_ip(response)
            raw["server_headers"] = _server_headers(response)
        except PlaywrightError as exc:
            raw["error"] = _short_error(exc)
        try:
            page.wait_for_load_state("networkidle", timeout=IDLE_TIMEOUT_MS)
        except PlaywrightError:
            pass

        page.remove_listener("request", on_request)
        page.remove_listener("response", on_response)
        if page.url.startswith(("http://", "https://")):
            raw["final_url"] = page.url

        try:
            if raw["error"] is not None and raw["final_url"] is None:
                raise PlaywrightError("no page to capture")
            raw["html"] = _cap(page.content(), HTML_CAP)
            raw["page_text"] = _cap(page.evaluate("() => document.body ? document.body.innerText : ''"), TEXT_CAP)
        except PlaywrightError:
            pass

        raw["scripts"] = _collect_scripts(page, script_responses)

        privacy_url = None
        if raw["error"] is None:
            try:
                site_domain = _registrable(urlsplit(raw["final_url"] or url).hostname)
                privacy_url = page.evaluate(FIND_PRIVACY_LINK_JS, {"words": PRIVACY_WORDS, "siteDomain": site_domain})
            except PlaywrightError:
                privacy_url = None
        page.close()

        if raw["final_url"]:
            parts = urlsplit(raw["final_url"])
            origin = f"{parts.scheme}://{parts.netloc}"
            raw["robots_txt"] = _get_text_file(context, origin, "/robots.txt")
            raw["llms_txt"] = _get_text_file(context, origin, "/llms.txt")
        if privacy_url:
            raw["privacy_policy"] = _fetch_privacy(context, privacy_url)
    except Exception as exc:  # never crash the batch
        raw["error"] = raw["error"] or _short_error(exc)
    finally:
        context.close()
    return raw


def _server_ip(response):
    """IP of the server that answered the main document, from the load already made. None if unknown."""
    try:
        addr = response.server_addr() if response else None
    except Exception:
        return None
    ip = (addr or {}).get("ipAddress")
    return ip.strip("[]") if ip else None


def _server_headers(response):
    """Lowercase-keyed subset of the main response headers that hint at the host or CDN."""
    if not response:
        return {}
    try:
        headers = response.all_headers()
    except Exception:
        try:
            headers = response.headers
        except Exception:
            return {}
    lower = {k.lower(): v for k, v in (headers or {}).items()}
    return {k: lower[k] for k in SERVER_HEADERS if k in lower}


def _collect_scripts(page, script_responses):
    scripts = []
    seen = set()
    for resp in script_responses:
        if resp.url in seen:
            continue
        seen.add(resp.url)
        try:
            content = _cap(resp.text(), SCRIPT_CAP)
        except Exception:
            content = None
        scripts.append({"src": resp.url, "inline": False, "content": content})
    try:
        dom_scripts = page.evaluate(COLLECT_SCRIPTS_JS)
    except PlaywrightError:
        dom_scripts = []
    for s in dom_scripts:
        if s["src"]:
            if s["src"] not in seen:
                seen.add(s["src"])
                scripts.append({"src": s["src"], "inline": False, "content": None})
        elif s["content"] and s["content"].strip():
            scripts.append({"src": None, "inline": True, "content": _cap(s["content"], SCRIPT_CAP)})
    return scripts


def _short_error(exc):
    msg = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
    if msg.startswith("Page.goto: "):
        msg = msg[len("Page.goto: "):]
    return msg[:200]


def write_raw(raw, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / raw_filename(raw["site"])
    path.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def summary_line(raw):
    status = raw["status"] if raw["status"] is not None else "ERR"
    line = (
        f"{raw['site']}  {status}  {len(raw['scripts'])} scripts  "
        f"privacy: {'yes' if raw['privacy_policy'] else 'no'}  "
        f"llms: {'yes' if raw['llms_txt'] is not None else 'no'}"
    )
    if raw["error"]:
        line += f"  error: {raw['error']}"
    return line


def run(sites_path, out_dir):
    """Fetch every site in sites_path and write one raw file each. Returns the written paths."""
    entries = read_site_entries(sites_path)
    paths = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for url, label in entries:
                raw = fetch_site(browser, url, label)
                paths.append(write_raw(raw, out_dir))
                print(summary_line(raw), flush=True)
        finally:
            browser.close()
    return paths
