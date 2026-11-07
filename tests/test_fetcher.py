import functools
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from scan import fetcher

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "cafe-demo"


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
    f.write_text("# comment\n\nexample.ie\nhttp://localhost:8765/\nhttps://a.example/x\n", encoding="utf-8")
    assert fetcher.read_sites(f) == ["https://example.ie/", "http://localhost:8765/", "https://a.example/x"]


def test_failed_site_still_writes_file(tmp_path):
    sites = tmp_path / "sites.txt"
    sites.write_text("http://127.0.0.1:9/\n", encoding="utf-8")
    [path] = fetcher.run(sites, tmp_path / "raw")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert path.name == "127.0.0.1_9.json"
    assert data["error"]
    assert data["scripts"] == [] and data["privacy_policy"] is None and data["llms_txt"] is None
