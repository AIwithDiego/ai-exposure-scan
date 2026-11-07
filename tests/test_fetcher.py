import functools
import json
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scan import fetcher  # noqa: E402

FIXTURE = ROOT / "fixtures" / "cafe-demo"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def fixture_url():
    handler = functools.partial(QuietHandler, directory=str(FIXTURE))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://localhost:{server.server_address[1]}/"
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def raw(fixture_url, tmp_path_factory):
    tmp = tmp_path_factory.mktemp("fetch")
    sites = tmp / "sites.txt"
    sites.write_text(f"# fixture\n\n{fixture_url}\n", encoding="utf-8")
    paths = fetcher.run(sites, tmp / "raw")
    assert len(paths) == 1
    port = fixture_url.rsplit(":", 1)[1].strip("/")
    assert paths[0].name == f"localhost_{port}.json"
    return json.loads(paths[0].read_text(encoding="utf-8"))


def test_matches_contract_shape(raw, fixture_url):
    expected = {
        "site", "url", "final_url", "fetched_at", "status", "error", "html", "page_text",
        "scripts", "requests", "robots_txt", "llms_txt", "privacy_policy",
    }
    assert set(raw) == expected
    assert raw["url"] == fixture_url
    assert raw["status"] == 200
    assert raw["error"] is None
    assert "Bella's Café" in raw["page_text"]
    for s in raw["scripts"]:
        assert set(s) == {"src", "inline", "content"}
    for r in raw["requests"]:
        assert set(r) == {"url", "domain", "method", "resource_type"}


def test_captures_widget_script_and_inline_config(raw):
    external = [s for s in raw["scripts"] if not s["inline"]]
    inline = [s for s in raw["scripts"] if s["inline"]]
    assert any(s["src"].endswith("/js/menu-assistant.js") and "OPENAI_KEY" in s["content"] for s in external)
    assert any("intercomSettings" in s["content"] and s["src"] is None for s in inline)


def test_privacy_policy_text(raw):
    assert raw["privacy_policy"]["url"].endswith("/privacy.html")
    assert "Intercom" in raw["privacy_policy"]["text"]


def test_robots_and_llms(raw):
    assert raw["llms_txt"] and "MCP server" in raw["llms_txt"]
    assert "GPTBot" in raw["robots_txt"]


def test_passive_only(raw):
    paths = {r["url"].split("localhost", 1)[1].split("/", 1)[1] for r in raw["requests"]}
    assert paths <= {"", "style.css", "js/menu-assistant.js", "favicon.ico"}
    assert not any("api.openai.com" in r["url"] for r in raw["requests"])


def test_read_sites(tmp_path):
    f = tmp_path / "sites.txt"
    f.write_text("# comment\n\nexample.ie\nhttp://localhost:8765/\nhttps://a.example/x\nexample.com?view=shop\n",
                 encoding="utf-8")
    assert fetcher.read_sites(f) == [
        "https://example.ie/", "http://localhost:8765/", "https://a.example/x", "https://example.com/?view=shop",
    ]


def test_read_site_entries_labels(tmp_path):
    f = tmp_path / "sites.txt"
    f.write_text("http://localhost:8765/ | Bella's Café (demo)\nexample.ie\nexample.com |  \n", encoding="utf-8")
    assert fetcher.read_site_entries(f) == [
        ("http://localhost:8765/", "Bella's Café (demo)"), ("https://example.ie/", None), ("https://example.com/", None),
    ]
    assert fetcher.read_sites(f) == ["http://localhost:8765/", "https://example.ie/", "https://example.com/"]
    f.write_text("https://a.example/?q=1|2 | Shop\nhttps://b.example/?q=1|2\n", encoding="utf-8")
    assert fetcher.read_site_entries(f) == [("https://a.example/?q=1|2", "Shop"), ("https://b.example/?q=1|2", None)]
    assert fetcher.empty_raw("http://localhost:8765/", "Bella's Café (demo)")["label"] == "Bella's Café (demo)"
    assert "label" not in fetcher.empty_raw("https://example.ie/")


def test_failed_site_still_writes_file(tmp_path):
    sites = tmp_path / "sites.txt"
    sites.write_text("http://127.0.0.1:9/\n", encoding="utf-8")
    [path] = fetcher.run(sites, tmp_path / "raw")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert path.name == "127.0.0.1_9.json"
    assert data["error"]
    assert data["scripts"] == [] and data["privacy_policy"] is None and data["llms_txt"] is None


@pytest.mark.parametrize("link, expected", [
    ('<a href="#privacy">Privacy</a>', None),
    ('<a href="/#/privacy">Privacy</a>', "/#/privacy"),
])
def test_privacy_link_anchors(tmp_path, link, expected):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text(f'{link}<h2 id="privacy">Privacy</h2>', encoding="utf-8")
    policy = _fetch_local(site, tmp_path)["privacy_policy"]
    if expected is None:
        assert policy is None
    else:
        assert policy["url"].endswith(expected) and "Privacy" in policy["text"]


def test_non_utf8_text_files_do_not_fail_site(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<p>Caf\u00e9</p>", encoding="utf-8")
    (site / "robots.txt").write_bytes("User-agent: *\n# Caf\u00e9\nDisallow:\n".encode("latin-1"))
    (site / "llms.txt").write_bytes(b"# Caf\xe9 \xff\n")
    raw = _fetch_local(site, tmp_path)
    assert raw["error"] is None and raw["status"] == 200
    assert "User-agent: *" in raw["robots_txt"] and "\ufffd" in raw["robots_txt"]
    assert raw["llms_txt"].startswith("# Caf")


@pytest.fixture
def privacy_fetches(monkeypatch):
    """Record every privacy URL the fetcher tries to load; only localhost ones are actually loaded."""
    calls = []
    real = fetcher._fetch_privacy

    def spy(context, url):
        calls.append(url)
        return real(context, url) if urlsplit(url).hostname == "localhost" else None

    monkeypatch.setattr(fetcher, "_fetch_privacy", spy)
    return calls


def test_consent_banner_privacy_links_are_ignored(tmp_path, privacy_fetches):
    raw = _fetch_local(ROOT / "fixtures" / "cookiebot-site", tmp_path)
    assert raw["error"] is None and raw["status"] == 200
    assert raw["privacy_policy"] is None
    assert privacy_fetches == []
    third_party = {"cookiebot.com", "www.hubspot.com", "policies.google.com"}
    assert not any(r["domain"] in third_party for r in raw["requests"])


def test_same_site_privacy_link_wins_over_banner_links(tmp_path, privacy_fetches):
    raw = _fetch_local(ROOT / "fixtures" / "cookiebot-same-site", tmp_path)
    policy = raw["privacy_policy"]
    assert urlsplit(policy["url"]).hostname == "localhost"
    assert urlsplit(policy["url"]).path.startswith("/privacy")
    assert "data controller" in policy["text"]
    assert all(urlsplit(u).hostname == "localhost" for u in privacy_fetches)


@pytest.mark.parametrize("host, expected", [
    ("www.zexel.io", "zexel.io"),
    ("ZEXEL.IO", "zexel.io"),
    ("shop.example.ie", "example.ie"),
    ("www.example.co.uk", "example.co.uk"),
    ("a.b.example.com.au", "example.com.au"),
    ("co.uk", "co.uk"),
    ("localhost", "localhost"),
    ("127.0.0.1", "127.0.0.1"),
])
def test_registrable(host, expected):
    assert fetcher._registrable(host) == expected


def _fetch_local(site, tmp_path):
    handler = functools.partial(QuietHandler, directory=str(site))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        sites = tmp_path / "sites.txt"
        sites.write_text(f"http://localhost:{server.server_address[1]}/\n", encoding="utf-8")
        [path] = fetcher.run(sites, tmp_path / "raw")
        return json.loads(path.read_text(encoding="utf-8"))
    finally:
        server.shutdown()
        server.server_close()
