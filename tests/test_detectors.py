import copy
import json
import re
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scan import detectors  # noqa: E402
from scan.cli import main as cli_main  # noqa: E402
from scan.score import compute_score, merge_findings  # noqa: E402

RAW = Path(__file__).resolve().parent / "raw" / "cafe-demo.json"
FIXTURE_JS = ROOT / "fixtures" / "cafe-demo" / "js" / "menu-assistant.js"


def load_raw():
    return json.loads(RAW.read_text(encoding="utf-8"))


def fixture_key():
    return re.search(r'"(sk-proj-[A-Za-z0-9]+)"', FIXTURE_JS.read_text()).group(1)


@pytest.fixture
def out_dir(tmp_path):
    (tmp_path / "raw").mkdir()
    shutil.copy(RAW, tmp_path / "raw" / "cafe-demo.json")
    return tmp_path


def run_detect(out_dir):
    assert cli_main(["detect", "--out", str(out_dir)]) == 0
    return json.loads((out_dir / "findings.json").read_text(encoding="utf-8"))


def test_cli_detect_finds_expected_types(out_dir):
    data = run_detect(out_dir)
    [site] = data["sites"]
    types = {f["type"] for f in site["findings"]}
    assert {"chatbot", "data_transfer", "key_leak", "agent_ready"} <= types
    assert site["site"] == "localhost:8765"
    assert site["score"] == compute_score(site["findings"])


def test_findings_match_contract(out_dir):
    data = run_detect(out_dir)
    assert set(data) == {"generated_at", "sites"}
    for site in data["sites"]:
        assert set(site) == {"site", "final_url", "status", "error", "score", "findings"}
        ids = [f["id"] for f in site["findings"]]
        assert len(ids) == len(set(ids))
        for f in site["findings"]:
            assert f["id"].startswith(f"{site['site']}:{f['type']}:")
            assert f["type"] in {"chatbot", "data_transfer", "key_leak", "disclosure", "agent_ready"}
            assert f["severity"] in {"high", "medium", "low", "info"}
            assert f["method"] == "detected"
            assert f["evidence"]["where"] and f["evidence"]["snippet"]
            assert len(f["evidence"]["snippet"]) <= 200
            assert len(f["title"]) < 70
            assert f["fix"]


def test_no_full_key_anywhere_in_output(out_dir, capsys):
    data = run_detect(out_dir)
    text = (out_dir / "findings.json").read_text(encoding="utf-8") + capsys.readouterr().out
    key = fixture_key()
    leaked = key in text
    assert not leaked, "the full fixture key appears in findings.json or stdout"
    [leak] = [f for f in data["sites"][0]["findings"] if f["type"] == "key_leak"]
    assert detectors.mask_key(key) in leak["evidence"]["snippet"]
    assert leak["severity"] == "high"
    assert leak["meta"]["key_type"] == "OpenAI"
    assert leak["evidence"]["where"].endswith("/js/menu-assistant.js")


def test_site_entry_carries_optional_label():
    raw = load_raw()
    assert "label" not in detectors.site_entry(raw, [])
    entry = detectors.site_entry({**raw, "label": "Bella's Café (demo)"}, [])
    assert entry["label"] == "Bella's Café (demo)"
    assert entry["site"] == raw["site"]
    key = fixture_key()
    masked = detectors.site_entry({**raw, "label": f"Demo {key}"}, [])["label"]
    assert key not in masked and masked == f"Demo {detectors.mask_key(key)}"


def test_mask_key():
    assert detectors.mask_key("sk-proj-ABCDEFGHIJKLMNOPwxyz") == "sk-proj-…wxyz"


def test_chatbot_and_data_transfer():
    raw = load_raw()
    bots = detectors.chatbots(raw)
    assert [b["meta"]["vendor"] for b in bots] == ["Intercom"]
    assert bots[0]["severity"] == "info"
    [dt] = detectors.data_transfer(raw, bots)
    assert dt["severity"] == "low"
    assert dt["title"] == "Chat messages likely go to the US (Intercom)"
    assert "EU data hosting" in dt["fix"]


def test_eu_vendor_has_no_data_transfer():
    raw = load_raw()
    raw["scripts"].append({"src": "https://client.crisp.chat/l.js", "inline": False, "content": None})
    bots = detectors.chatbots(raw)
    assert {b["meta"]["vendor"] for b in bots} == {"Intercom", "Crisp"}
    assert [d["meta"]["vendor"] for d in detectors.data_transfer(raw, bots)] == ["Intercom"]


def test_vendor_matched_by_request_domain():
    raw = load_raw()
    raw["requests"].append({"url": "https://code.tidio.co/abc.js", "domain": "code.tidio.co",
                            "method": "GET", "resource_type": "script"})
    assert "Tidio" in {b["meta"]["vendor"] for b in detectors.chatbots(raw)}


def test_anthropic_key_not_double_counted_and_google_low():
    raw = load_raw()
    ant = "sk-ant-" + "A1b2C3d4" * 4
    goog = "AIza" + "B" * 35
    raw["scripts"].append({"src": None, "inline": True, "content": f'const a="{ant}"; const g="{goog}";'})
    leaks = detectors.key_leaks(raw)
    types = sorted(f["meta"]["key_type"] for f in leaks)
    assert types == ["Anthropic", "Google", "OpenAI"]
    google = next(f for f in leaks if f["meta"]["key_type"] == "Google")
    assert google["severity"] == "low"
    text = json.dumps(leaks, ensure_ascii=False)
    assert ant not in text and goog not in text
    assert any(f["evidence"]["where"] == "inline script" for f in leaks)


def test_css_class_is_not_a_key():
    raw = load_raw()
    raw["html"] += '<div class="task-list-item-with-a-very-long-name-here">'
    assert len(detectors.key_leaks(raw)) == 1


def test_agent_ready_fixture():
    findings = {f["id"].split(":")[-1]: f for f in detectors.agent_ready(load_raw())}
    assert set(findings) == {"has-llms-txt", "crawler-rules", "mcp"}
    rules = findings["crawler-rules"]
    assert rules["meta"]["blocked"] == ["GPTBot", "CCBot"]
    assert rules["evidence"]["snippet"] == "User-agent: GPTBot | Disallow: / | User-agent: CCBot | Disallow: /"
    assert "bellas-cafe.example/mcp" in findings["mcp"]["evidence"]["snippet"]
    assert all(f["severity"] == "info" for f in findings.values())


def test_agent_ready_missing_files():
    raw = load_raw()
    raw.update(robots_txt=None, llms_txt=None, html="<p>no agents here</p>", page_text="")
    ids = {f["id"].split(":")[-1] for f in detectors.agent_ready(raw)}
    assert ids == {"no-llms-txt", "crawler-rules"}


@pytest.mark.parametrize("text, named", [
    ("# Shop\nWe like mcp a lot.", False),
    ("We build MCP servers for clients.\nSee https://shop.example/about", False),
    ("Our MCP server: https://shop.example/agents", True),
    ("Agents: https://mcp.shop.example/", True),
    ('<a href="https://shop.example/">Home</a>' + "x" * 300 + "<p>We build MCP servers for clients</p>", False),
])
def test_mcp_only_when_named(text, named):
    raw = load_raw()
    raw.update(llms_txt=text, html="", page_text="")
    assert ("mcp" in {f["id"].split(":")[-1] for f in detectors.agent_ready(raw)}) == named


def test_failed_site_has_null_score(out_dir):
    raw = load_raw()
    raw.update(site="down.example", error="timeout after 10 s", html=None, scripts=[], requests=[])
    (out_dir / "raw" / "down.example.json").write_text(json.dumps(raw), encoding="utf-8")
    data = run_detect(out_dir)
    down = next(s for s in data["sites"] if s["site"] == "down.example")
    assert down["score"] is None and down["findings"] == []


def test_failed_rescan_drops_old_judged_findings(out_dir):
    data = run_detect(out_dir)
    data["sites"][0]["findings"].append({
        "id": "localhost:8765:disclosure:x", "type": "disclosure", "title": "Old", "severity": "medium",
        "method": "judged", "evidence": {"where": "http://localhost:8765/", "snippet": "old"}, "fix": "x",
    })
    (out_dir / "findings.json").write_text(json.dumps(data), encoding="utf-8")
    raw = load_raw()
    raw.update(error="timeout after 10 s", html=None, scripts=[], requests=[])
    (out_dir / "raw" / "cafe-demo.json").write_text(json.dumps(raw), encoding="utf-8")
    site = run_detect(out_dir)["sites"][0]
    assert site["score"] is None and site["findings"] == []


def test_rerun_keeps_policy_findings_without_duplicates(out_dir):
    data = run_detect(out_dir)
    judged = {
        "id": "localhost:8765:disclosure:bot-not-ai", "type": "disclosure", "title": "Bot doesn't say it's AI",
        "severity": "medium", "method": "judged",
        "evidence": {"where": "http://localhost:8765/", "snippet": "Hi! I'm Bella"}, "fix": "Say it's AI.",
    }
    data["sites"][0]["findings"].append(judged)
    (out_dir / "findings.json").write_text(json.dumps(data), encoding="utf-8")
    first = run_detect(out_dir)["sites"][0]
    second = run_detect(out_dir)["sites"][0]
    assert first["findings"] == second["findings"]
    assert sum(f["id"] == judged["id"] for f in second["findings"]) == 1
    assert second["score"] == compute_score(second["findings"])


def test_score_and_merge():
    f = lambda i, s: {"id": i, "severity": s}
    assert compute_score([f("a", "high"), f("b", "medium"), f("c", "low"), f("d", "info")]) == 62
    assert compute_score([f(str(i), "high") for i in range(5)]) == 0
    assert compute_score([], error="boom") is None
    merged = merge_findings([f("a", "low"), f("b", "info")], [f("a", "high")])
    assert sorted((m["id"], m["severity"]) for m in merged) == [("a", "high"), ("b", "info")]


def test_detect_is_stable():
    raw = load_raw()
    assert detectors.detect(copy.deepcopy(raw)) == detectors.detect(copy.deepcopy(raw))


def test_keys_in_urls_are_masked():
    key = fixture_key()
    raw = load_raw()
    raw["scripts"].append({"src": f"https://widget.intercom.io/widget/x?k={key}", "content": ""})
    raw.update(llms_txt=f"Our MCP server: https://shop.example/mcp?token={key}", html="", page_text="")
    out = json.dumps(detectors.detect(raw), ensure_ascii=False)
    assert key not in out and detectors.mask_key(key) in out


def _crawler_meta(robots):
    raw = load_raw()
    raw["robots_txt"] = robots
    return next(f for f in detectors.agent_ready(raw) if f["id"].endswith("crawler-rules"))["meta"]


def test_crawler_rules_combine_groups():
    meta = _crawler_meta("User-agent: GPTBot\nAllow: /menu\n\nUser-agent: *\nAllow: /\n\nUser-agent: GPTBot\nDisallow: /\n")
    assert "GPTBot" in meta["blocked"] and "GPTBot" not in meta["allowed"]


def test_allow_root_beats_disallow_root():
    meta = _crawler_meta("User-agent: GPTBot\nDisallow: /\nAllow: /\n")
    assert "GPTBot" in meta["allowed"] and "GPTBot" not in meta["blocked"]


def test_empty_agent_files_still_have_evidence():
    raw = load_raw()
    raw.update(robots_txt="", llms_txt="  \n")
    assert all(f["evidence"]["snippet"] for f in detectors.agent_ready(raw))


OPENAI = "sk-proj-" + "Qw3rTy8uIoPaSdFgHjKlZx"
HF = "hf_" + "Mn7bVcXz5LkJhGfDsAqWeRtYuIoP9a"
MAPS_A = "AIza" + "SyA1b2C3d4E5f6G7h8I9j0KlMnOpQrStUvW"
MAPS_B = "AIza" + "SyZ9y8X7w6V5u4T3s2R1q0PoNmLkJiHgFeD"


def _no_hidden_part(out, *keys):
    for key in keys:
        hidden = key[8:-4]
        assert not any(hidden[i:i + 5] in out for i in range(len(hidden) - 4)), key


@pytest.mark.parametrize("content", [
    f'const a="{OPENAI}",b="{HF}";',
    f'maps=["{MAPS_A}","{MAPS_B}"]',
])
def test_adjacent_keys_are_masked_before_cutting(content):
    raw = load_raw()
    raw.update(html="", scripts=[{"src": None, "inline": True, "content": content}])
    leaks = detectors.key_leaks(raw)
    assert len(leaks) == 2
    _no_hidden_part(json.dumps(leaks, ensure_ascii=False), OPENAI, HF, MAPS_A, MAPS_B)


def test_line_around_masks_key_cut_by_window():
    text = "intercomSettings " + "word " * 34 + OPENAI + " tail"
    snippet = detectors.line_around(text, 0, len("intercomSettings"))
    assert snippet.startswith("intercomSettings")
    _no_hidden_part(snippet, OPENAI)


def test_vendor_match_ignores_query_string():
    raw = load_raw()
    raw.update(scripts=[{"src": "https://cdn.example/app.js?from=code.tidio.co", "inline": False, "content": ""}],
               requests=[{"url": "https://cdn.example/p?ref=code.tidio.co", "domain": "cdn.example",
                          "method": "GET", "resource_type": "xhr"}])
    assert "Tidio" not in {b["meta"]["vendor"] for b in detectors.chatbots(raw)}
