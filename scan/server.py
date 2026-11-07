"""Local web server: the dashboard plus a scan-one-site API.

POST /api/scan     {"url": "example.ie", "label": "optional"} -> the site entry (docs/contract.md section 2)
GET  /api/findings -> out/findings.json, or an empty findings document
anything else      -> dashboard/dist, index.html for unknown paths

Standard library only (plus the pipeline parts). One scan at a time.
"""
import ipaddress
import json
import mimetypes
import os
import re
import socket
import sys
import tempfile
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit

from scan import detectors, policy
from scan.detectors import mask_all_keys
from scan.score import compute_score, merge_findings
from scan.validate import validate

DIST = Path(__file__).resolve().parent.parent / "dashboard" / "dist"
SCAN_TIMEOUT = 60  # seconds
FIXTURE_HOSTS = {"localhost", "127.0.0.1"}
FIXTURE_PORT = 8765
MAX_BODY = 8 * 1024
MAX_URL = 2048
MAX_LABEL = 80
HAS_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")

SCAN_LOCK = threading.Lock()   # one browser scan at a time; held by the worker thread
WRITE_LOCK = threading.Lock()  # read-modify-write of findings.json


class Rejected(ValueError):
    """The URL can't be scanned; str(exc) is the plain message for the user."""


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_fixture(host, port, allow_fixture):
    return allow_fixture and host in FIXTURE_HOSTS and port == FIXTURE_PORT


def _blocked_ip(ip):
    ip = ipaddress.ip_address(ip.split("%", 1)[0])
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    return (ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved
            or ip.is_multicast or ip.is_unspecified)


def check_host(host, port, allow_fixture=False):
    """Raise Rejected unless every address the host resolves to is public (or it's the allowed fixture)."""
    if _is_fixture(host, port, allow_fixture):
        return
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError):
        raise Rejected(f"Couldn't find a website at {host}. Check the address and try again.")
    ips = {info[4][0] for info in infos}
    if not ips or any(_blocked_ip(ip) for ip in ips):
        raise Rejected(f"{host} points to a private or local network address, so we won't scan it.")


def _split(text):
    try:
        parts = urlsplit(text)
        parts.hostname, parts.port  # noqa: B018 - both raise ValueError on malformed hosts/ports
        return parts
    except ValueError:
        raise Rejected("That doesn't look like a website address. Check it and try again.")


def normalise_url(text, allow_fixture=False):
    """Clean up what the user typed into an http(s) URL with a path. Raise Rejected if it isn't scannable."""
    if not isinstance(text, str) or not text.strip():
        raise Rejected("Enter a website address, e.g. example.ie")
    text = text.strip()
    if len(text) > MAX_URL:
        raise Rejected("That address is too long.")
    if not HAS_SCHEME.match(text):
        bare = _split("//" + text).hostname or ""
        text = ("http://" if bare in FIXTURE_HOSTS else "https://") + text
    if HAS_SCHEME.match(text).group(0)[:-3].lower() not in ("http", "https"):
        raise Rejected("Only http:// and https:// websites can be scanned.")
    parts = _split(text)
    port = parts.port
    host = (parts.hostname or "").rstrip(".")
    if not host:
        raise Rejected("That address has no website name in it.")
    if parts.username is not None or parts.password is not None:
        raise Rejected("Addresses with a username or password can't be scanned.")
    check_host(host, port or (443 if parts.scheme.lower() == "https" else 80), allow_fixture)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", parts.query, ""))


def _url_allowed(url, allow_fixture):
    try:
        parts = urlsplit(url)
        check_host((parts.hostname or "").rstrip("."), parts.port or (443 if parts.scheme == "https" else 80),
                   allow_fixture)
        return True
    except (Rejected, ValueError):
        return False


def error_entry(url, label, message):
    from scan.fetcher import empty_raw

    raw = empty_raw(url, label)
    raw["error"] = message
    return detectors.site_entry(raw, [])


def scan_site(url, label=None, allow_fixture=False):
    """Fetch one site in a fresh browser, run detectors and the policy reader, and return its site entry."""
    from playwright.sync_api import sync_playwright

    from scan import fetcher

    with tempfile.TemporaryDirectory(prefix="ai-exposure-scan-") as tmp:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                raw = fetcher.fetch_site(browser, url, label)
            finally:
                browser.close()
        fetcher.write_raw(raw, tmp)  # raw HTML and scripts never outlive the scan
        if raw.get("final_url") and not _url_allowed(raw["final_url"], allow_fixture):
            return error_entry(url, label, "The site redirected to a private or local address, so we stopped.")
        findings = detectors.detect(raw)
        findings = merge_findings(findings, policy.judge(raw, findings, policy.model_backend()))
        entry = detectors.site_entry(raw, findings)
    for field in ("final_url", "error"):
        if entry.get(field):
            entry[field] = mask_all_keys(entry[field])
    return entry


def run_scan(url, label=None, allow_fixture=False, timeout=None):
    """Scan in a worker thread with a hard timeout. Returns the site entry, or None if a scan is running."""
    if not SCAN_LOCK.acquire(blocking=False):
        return None
    result = {}

    def work():
        try:
            result["entry"] = scan_site(url, label, allow_fixture)
        except Exception as exc:  # never leave the lock held or the request hanging
            result["entry"] = error_entry(url, label, f"The scan failed: {type(exc).__name__}")
        finally:
            SCAN_LOCK.release()

    worker = threading.Thread(target=work, name="scan-worker", daemon=True)
    worker.start()
    limit = SCAN_TIMEOUT if timeout is None else timeout
    worker.join(limit)
    if worker.is_alive():
        return error_entry(url, label, f"The scan took longer than {limit:g} seconds and was stopped.")
    return result["entry"]


def load_findings(path):
    path = Path(path)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("sites"), list):
                return data
        except (OSError, json.JSONDecodeError):
            pass
    return {"generated_at": _now(), "sites": []}


def merge_into_findings(path, entry):
    """Replace or add `entry` in findings.json, rescore every site, validate, write atomically.
    Returns the list of contract problems (nothing is written if there are any)."""
    path = Path(path)
    with WRITE_LOCK:
        data = load_findings(path)
        sites = data["sites"]
        for i, s in enumerate(sites):
            if isinstance(s, dict) and s.get("site") == entry["site"]:
                sites[i] = entry
                break
        else:
            sites.append(entry)
        for s in sites:
            if isinstance(s, dict):
                s["score"] = compute_score(s.get("findings", []), s.get("error"))
        data = {"generated_at": _now(), **{k: v for k, v in data.items() if k != "generated_at"}}
        problems = validate(data)
        if problems:
            return problems
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".findings-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
    return []


def log_scan(entry):
    status = "error" if entry.get("error") else entry.get("status")
    score = "-" if entry.get("score") is None else entry["score"]
    print(mask_all_keys(f"scan {entry['site']} status={status} score={score}"), file=sys.stderr, flush=True)


class Handler(BaseHTTPRequestHandler):
    server_version = "AIExposureScan"
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):  # one line per scan, logged by log_scan
        pass

    def _send(self, code, body, content_type):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _text(self, code, message):
        self._send(code, message + "\n", "text/plain; charset=utf-8")

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def _path(self):
        return urlsplit(self.path).path

    def do_GET(self):
        path = self._path()
        if path == "/api/findings":
            return self._json(200, load_findings(Path(self.server.out_dir) / "findings.json"))
        if path == "/api" or path.startswith("/api/"):
            return self._text(404, "Not found")
        return self._static(path)

    do_HEAD = do_GET

    def do_POST(self):
        if self._path() != "/api/scan":
            return self._text(404, "Not found")
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length <= 0 or length > MAX_BODY:
            self.close_connection = True
            return self._text(400, "Send a JSON body like {\"url\": \"example.ie\"}.")
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._text(400, "Send a JSON body like {\"url\": \"example.ie\"}.")
        if not isinstance(body, dict):
            return self._text(400, "Send a JSON body like {\"url\": \"example.ie\"}.")
        label = body.get("label")
        label = label.strip()[:MAX_LABEL] if isinstance(label, str) and label.strip() else None
        try:
            url = normalise_url(body.get("url"), self.server.allow_fixture)
        except Rejected as exc:
            return self._text(400, str(exc))

        entry = run_scan(url, label, self.server.allow_fixture)
        if entry is None:
            return self._text(429, "A scan is already running, try again in a moment")
        problems = merge_into_findings(Path(self.server.out_dir) / "findings.json", entry)
        log_scan(entry)
        if problems:
            print(f"scan {entry['site']}: findings.json not written, {len(problems)} contract problem(s)",
                  file=sys.stderr, flush=True)
            return self._text(500, "The scan finished but the results didn't pass the format check.")
        return self._json(200, entry)

    def do_PUT(self):
        self._text(405, "Method not allowed")

    do_DELETE = do_PATCH = do_PUT

    def _static(self, path):
        root = Path(self.server.dist).resolve()
        index = root / "index.html"
        if not index.is_file():
            return self._text(503, "The dashboard isn't built yet. Run: cd dashboard && npm run build")
        target = (root / unquote(path).lstrip("/")).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            target = index
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json", "image/svg+xml"):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype)


def make_server(port=8000, out_dir="out", allow_fixture=False, host="127.0.0.1", dist=DIST):
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.out_dir = str(out_dir)
    server.allow_fixture = bool(allow_fixture)
    server.dist = str(dist)
    return server


def serve(port=8000, out_dir="out", allow_fixture=False):
    server = make_server(port, out_dir, allow_fixture)
    print(f"serving on http://localhost:{server.server_address[1]}"
          f"{'  (fixture on :%d allowed)' % FIXTURE_PORT if allow_fixture else ''}", file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
