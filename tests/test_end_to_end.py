import functools
import json
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scan import cli  # noqa: E402
from scan.validate import TYPES, validate  # noqa: E402

FIXTURE = ROOT / "fixtures" / "cafe-demo"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def findings(tmp_path_factory):
    handler = functools.partial(QuietHandler, directory=str(FIXTURE))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://localhost:{server.server_address[1]}/"
    tmp = tmp_path_factory.mktemp("e2e")
    sites = tmp / "sites.txt"
    sites.write_text(url + "\n", encoding="utf-8")
    mp = pytest.MonkeyPatch()
    mp.delenv("ANTHROPIC_API_KEY", raising=False)
    mp.delenv("OPENAI_API_KEY", raising=False)
    try:
        code = cli.main(["all", "--sites", str(sites), "--out", str(tmp / "out"), "--no-dashboard"])
    finally:
        mp.undo()
        server.shutdown()
        server.server_close()
    assert code == 0
    return json.loads((tmp / "out" / "findings.json").read_text(encoding="utf-8"))


def test_validates_against_contract(findings):
    assert validate(findings) == []


def test_fixture_has_every_finding_type(findings):
    (site,) = findings["sites"]
    assert {f["type"] for f in site["findings"]} == TYPES


def test_fixture_planted_findings(findings):
    (site,) = findings["sites"]
    by_slug = {f["id"].split(":", 3)[-1]: f for f in site["findings"]}
    leak = next(f for f in site["findings"] if f["type"] == "key_leak")
    assert leak["severity"] == "high" and leak["meta"]["key_type"] == "OpenAI"
    assert "DEMO0000FAKE" not in json.dumps(findings)
    assert by_slug["intercom"]["meta"]["vendor"] == "Intercom"
    assert by_slug["bot-not-ai"]["severity"] == "medium"
    assert by_slug["policy-openai"]["severity"] == "medium"
    assert {"has-llms-txt", "crawler-rules", "mcp"} <= by_slug.keys()
    assert site["score"] == 52


def test_validator_catches_contract_breaks(findings):
    broken = json.loads(json.dumps(findings))
    site = broken["sites"][0]
    site["score"] = 101
    site["findings"][0]["severity"] = "critical"
    site["findings"].append(dict(site["findings"][1]))
    del site["findings"][2]["fix"]
    problems = " | ".join(validate(broken))
    for expected in ("score", "bad severity", "duplicate id", "missing ['fix']"):
        assert expected in problems


def test_validator_reports_bad_sites_without_crashing(findings):
    broken = json.loads(json.dumps(findings))
    site = broken["sites"][0]
    site["findings"].append(None)
    site["final_url"] = "http://localhost/?k=sk-proj-DEMO0000FAKE0000NOTAREALKEY0000cafe"
    broken["sites"].append({"site": None, "final_url": None, "status": 200, "error": None, "score": 100, "findings": []})
    problems = " | ".join(validate(broken))
    for expected in ("finding is not an object", "final_url contains an unmasked key", "site must be a non-empty string"):
        assert expected in problems


def test_all_drops_sites_not_in_the_list(tmp_path):
    raw = tmp_path / "out" / "raw"
    raw.mkdir(parents=True)
    (raw / "old.example.json").write_text("{}", encoding="utf-8")
    (raw / "localhost_8765.json").write_text("{}", encoding="utf-8")
    sites = tmp_path / "sites.txt"
    sites.write_text("http://localhost:8765/\n", encoding="utf-8")
    cli._drop_stale_raw(raw, sites)
    assert [p.name for p in raw.glob("*.json")] == ["localhost_8765.json"]
