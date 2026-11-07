import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scan import policy  # noqa: E402
from scan.cli import main as cli_main  # noqa: E402
from scan.score import compute_score  # noqa: E402

RAW = Path(__file__).resolve().parent / "raw" / "cafe-demo.json"
SITE = "localhost:8765"


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def load_raw():
    return json.loads(RAW.read_text(encoding="utf-8"))


def write_raw(out_dir, raw):
    (out_dir / "raw").mkdir(exist_ok=True)
    (out_dir / "raw" / f"{raw['site'].replace(':', '_')}.json").write_text(json.dumps(raw), encoding="utf-8")


def detect_and_policy(out_dir):
    assert cli_main(["detect", "--out", str(out_dir)]) == 0
    assert cli_main(["policy", "--out", str(out_dir)]) == 0
    return json.loads((out_dir / "findings.json").read_text(encoding="utf-8"))


def site(data, name=SITE):
    return next(s for s in data["sites"] if s["site"] == name)


def disclosures(data, name=SITE):
    return {f["id"].split(":disclosure:")[1]: f for f in site(data, name)["findings"] if f["type"] == "disclosure"}


def chatbot(vendor):
    return {"id": f"{SITE}:chatbot:{vendor.lower()}", "type": "chatbot", "title": f"{vendor} chat widget",
            "severity": "info", "method": "detected", "evidence": {"where": "x", "snippet": "x"},
            "fix": "x", "meta": {"vendor": vendor}}


def test_fixture_adds_disclosure_findings(tmp_path):
    write_raw(tmp_path, load_raw())
    found = disclosures(detect_and_policy(tmp_path))
    assert found["bot-not-ai"]["severity"] == "medium"
    assert found["bot-not-ai"]["evidence"]["snippet"] == "Hi! I'm Bella, how can I help with your order today?"
    assert found["policy-openai"]["severity"] == "medium"
    for f in found.values():
        assert f["method"] == "judged"
        assert f["meta"]["engine"] == "keywords"
        assert f["id"].startswith(f"{SITE}:disclosure:")
        assert len(f["evidence"]["snippet"]) <= 200
        assert f["evidence"]["where"] and f["fix"]


def test_missing_policy_is_medium(tmp_path):
    raw = load_raw()
    raw["privacy_policy"] = None
    write_raw(tmp_path, raw)
    f = disclosures(detect_and_policy(tmp_path))["no-policy"]
    assert f["severity"] == "medium"
    assert f["title"] == "No privacy policy found on the homepage"
    assert f["evidence"]["where"] == raw["final_url"]


def test_policy_naming_vendor_has_no_vendor_finding():
    raw = load_raw()
    found = {f["id"] for f in policy.judge(raw, [chatbot("Intercom")])}
    assert f"{SITE}:disclosure:policy-intercom" not in found


def test_policy_silent_on_vendor_is_medium():
    raw = load_raw()
    found = {f["id"]: f for f in policy.judge(raw, [chatbot("Tidio")])}
    f = found[f"{SITE}:disclosure:policy-tidio"]
    assert f["severity"] == "medium"
    assert f["meta"]["vendor"] == "Tidio"
    assert f["evidence"]["where"] == raw["privacy_policy"]["url"]


def test_policy_mentioning_ai_quotes_the_sentence():
    raw = load_raw()
    raw["privacy_policy"]["text"] += "\n\nOur chatbot uses artificial intelligence from OpenAI."
    found = {f["id"]: f for f in policy.judge(raw, [chatbot("OpenAI API")])}
    assert f"{SITE}:disclosure:policy-openai" not in found
    assert found[f"{SITE}:disclosure:policy-ai"]["evidence"]["snippet"] == \
        "Our chatbot uses artificial intelligence from OpenAI."


def test_chatbot_without_greeting_is_unknown_low():
    raw = load_raw()
    raw["scripts"] = [{"src": "https://widget.intercom.io/widget/abc", "inline": False, "content": None}]
    found = {f["id"]: f for f in policy.judge(raw, [chatbot("Intercom")])}
    f = found[f"{SITE}:disclosure:bot-unknown"]
    assert f["severity"] == "low"
    assert "Couldn't tell" in f["title"]


def test_greeting_that_says_ai_is_not_a_problem():
    raw = load_raw()
    raw["scripts"][1]["content"] = 'window.intercomSettings = { greeting: "Hi, I\'m Bella, an AI assistant." };'
    found = {f["id"]: f for f in policy.judge(raw, [chatbot("Intercom")])}
    assert found[f"{SITE}:disclosure:bot-ai"]["severity"] == "info"
    assert f"{SITE}:disclosure:bot-not-ai" not in found


def test_no_chatbot_means_no_bot_question():
    raw = load_raw()
    assert not any(":bot-" in f["id"] for f in policy.judge(raw, []))


def test_second_run_does_not_duplicate(tmp_path):
    write_raw(tmp_path, load_raw())
    first = detect_and_policy(tmp_path)
    assert cli_main(["policy", "--out", str(tmp_path)]) == 0
    second = json.loads((tmp_path / "findings.json").read_text(encoding="utf-8"))
    ids = [f["id"] for f in site(second)["findings"]]
    assert len(ids) == len(set(ids))
    assert sorted(ids) == sorted(f["id"] for f in site(first)["findings"])
    assert site(second)["score"] == site(first)["score"]


def test_score_recomputed(tmp_path):
    write_raw(tmp_path, load_raw())
    assert cli_main(["detect", "--out", str(tmp_path)]) == 0
    before = site(json.loads((tmp_path / "findings.json").read_text(encoding="utf-8")))["score"]
    assert cli_main(["policy", "--out", str(tmp_path)]) == 0
    entry = site(json.loads((tmp_path / "findings.json").read_text(encoding="utf-8")))
    assert entry["score"] == compute_score(entry["findings"]) == before - 20


def test_error_site_is_skipped(tmp_path):
    raw = copy.deepcopy(load_raw())
    raw.update(site="broken.example", error="timeout", privacy_policy=None)
    write_raw(tmp_path, raw)
    data = detect_and_policy(tmp_path)
    entry = site(data, "broken.example")
    assert entry["score"] is None
    assert not any(f["type"] == "disclosure" for f in entry["findings"])


def test_keys_in_policy_are_masked_before_model_and_findings():
    raw = load_raw()
    key = "sk-proj-" + "A1" * 15
    raw["privacy_policy"]["url"] = f"https://example.ie/privacy?k={key}"
    raw["privacy_policy"]["text"] += f"\n\nOur assistant key is {key}."
    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        return '{"answer": "no", "quote": ""}'

    found = policy.judge(raw, [chatbot("Tidio")], ask)
    assert prompts and all(key not in p for p in prompts)
    assert all(key not in json.dumps(f) for f in found)
