import functools
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scan import server as scan_server  # noqa: E402
from scan.validate import validate  # noqa: E402

FIXTURE = ROOT / "fixtures" / "cafe-demo"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def fixture_port():
    handler = functools.partial(QuietHandler, directory=str(FIXTURE))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(autouse=True)
def no_model_keys(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def start(tmp_path, allow_fixture):
    dist = tmp_path / "dist"
    dist.mkdir(exist_ok=True)
    (dist / "index.html").write_text("<!doctype html><title>dashboard</title>", encoding="utf-8")
    httpd = scan_server.make_server(0, tmp_path / "out", allow_fixture=allow_fixture, dist=dist)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


@pytest.fixture
def api(tmp_path, monkeypatch, fixture_port):
    """Scan server with --allow-fixture; the fixture exception points at the test fixture's random port."""
    monkeypatch.setattr(scan_server, "FIXTURE_PORT", fixture_port)
    httpd, base = start(tmp_path, allow_fixture=True)
    yield base
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def strict_api(tmp_path):
    httpd, base = start(tmp_path, allow_fixture=False)
    yield base
    httpd.shutdown()
    httpd.server_close()


def post(base, body, timeout=90):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(f"{base}/api/scan", data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def get(base, path):
    with urllib.request.urlopen(f"{base}{path}", timeout=10) as r:
        return r.status, r.headers.get("Content-Type"), r.read().decode("utf-8")


def test_scan_fixture_merges_into_findings(api, tmp_path, fixture_port):
    out = tmp_path / "out" / "findings.json"
    out.parent.mkdir()
    old = {"site": "old.example", "final_url": "https://old.example/", "status": 200, "error": None,
           "score": 7, "findings": []}
    out.write_text(json.dumps({"generated_at": "2026-01-01T00:00:00Z", "sites": [old]}), encoding="utf-8")

    code, body = post(api, {"url": f"localhost:{fixture_port}", "label": "Bella's Café (demo)"})
    assert code == 200, body
    entry = json.loads(body)
    assert entry["site"] == f"localhost:{fixture_port}"
    assert entry["label"] == "Bella's Café (demo)"
    assert entry["score"] == 52
    assert "DEMO0000FAKE" not in body

    data = json.loads(out.read_text(encoding="utf-8"))
    assert validate(data) == []
    assert [s["site"] for s in data["sites"]] == ["old.example", entry["site"]]
    assert data["sites"][0]["score"] == 100  # rescored
    assert data["generated_at"] != "2026-01-01T00:00:00Z"

    assert post(api, {"url": f"http://localhost:{fixture_port}/"})[0] == 200
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data["sites"]) == 2 and validate(data) == []

    _, ctype, findings = get(api, "/api/findings")
    assert ctype.startswith("application/json") and json.loads(findings) == data


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/",
    "http://10.0.0.1/",
    "http://169.254.169.254/",
    "http://[::1]/",
    "http://0.0.0.0/",
    "file:///etc/passwd",
    "ftp://x/",
    "http://user:pass@example.com/",
    "http://[::1",
    "[::1",
    "http://example.com:99999/",
    "",
])
def test_rejects_unsafe_urls(strict_api, tmp_path, url):
    code, body = post(strict_api, {"url": url})
    assert code == 400
    assert body.strip() and not body.lstrip().startswith("{")
    assert not (tmp_path / "out" / "findings.json").exists()


def test_fixture_needs_allow_fixture(strict_api):
    code, body = post(strict_api, {"url": "http://localhost:8765"})
    assert code == 400 and "private or local" in body
    assert post(strict_api, {"url": "localhost:8765"})[0] == 400


def test_allow_fixture_only_opens_the_fixture_port(api):
    assert post(api, {"url": "http://localhost:9/"})[0] == 400
    assert post(api, {"url": "http://127.0.0.2:8765/"})[0] == 400


def test_second_concurrent_scan_gets_429(api, fixture_port):
    results = {}
    first = threading.Thread(target=lambda: results.update(first=post(api, {"url": f"localhost:{fixture_port}"})))
    first.start()
    deadline = time.time() + 10
    while not scan_server.SCAN_LOCK.locked() and time.time() < deadline:
        time.sleep(0.01)
    assert scan_server.SCAN_LOCK.locked()
    code, body = post(api, {"url": f"localhost:{fixture_port}"})
    first.join(90)
    assert code == 429 and "already running" in body
    assert results["first"][0] == 200


def test_timeout_gives_error_entry(api, tmp_path, monkeypatch, fixture_port):
    release = threading.Event()

    def slow_scan(url, label=None, allow_fixture=False):
        release.wait(10)
        raise AssertionError("result after timeout must be ignored")

    monkeypatch.setattr(scan_server, "scan_site", slow_scan)
    monkeypatch.setattr(scan_server, "SCAN_TIMEOUT", 0.3)
    try:
        code, body = post(api, {"url": f"localhost:{fixture_port}"})
    finally:
        release.set()
    assert code == 200
    entry = json.loads(body)
    assert entry["error"] and entry["score"] is None and entry["findings"] == []
    assert validate(json.loads((tmp_path / "out" / "findings.json").read_text(encoding="utf-8"))) == []


def test_findings_and_static_fallback(strict_api):
    _, ctype, body = get(strict_api, "/api/findings")
    data = json.loads(body)
    assert data["sites"] == [] and validate(data) == []
    for path in ("/", "/some/page", "/../../etc/passwd"):
        status, ctype, body = get(strict_api, path)
        assert status == 200 and ctype.startswith("text/html") and "dashboard" in body
    with pytest.raises(urllib.error.HTTPError) as err:
        get(strict_api, "/api/nope")
    assert err.value.code == 404


def test_bad_bodies(strict_api):
    req = urllib.request.Request(f"{strict_api}/api/scan", data=b"not json")
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(req, timeout=10)
    assert err.value.code == 400
    assert post(strict_api, ["example.ie"])[0] == 400


def test_failed_load_masks_keys_in_error(tmp_path, monkeypatch):
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        closed = s.getsockname()[1]
    monkeypatch.setattr(scan_server, "FIXTURE_PORT", closed)
    httpd, base = start(tmp_path, allow_fixture=True)
    try:
        key = "sk-ant-" + "A1b2C3d4" * 4
        code, body = post(base, {"url": f"http://localhost:{closed}/?k={key}"})
        assert code == 200
        entry = json.loads(body)
        assert entry["error"] and entry["score"] is None
        assert key not in body
        assert key not in (tmp_path / "out" / "findings.json").read_text(encoding="utf-8")
    finally:
        httpd.shutdown()
        httpd.server_close()
