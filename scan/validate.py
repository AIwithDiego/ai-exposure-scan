"""Check a findings.json dict against docs/contract.md section 2. Returns a list of problems."""
import json
import re
import sys
from datetime import datetime

from scan.detectors import key_spans
from scan.score import compute_score

TYPES = {"chatbot", "data_transfer", "key_leak", "disclosure", "agent_ready"}
SEVERITIES = {"high", "medium", "low", "info"}
METHODS = {"detected", "judged"}
SITE_KEYS = {"site", "final_url", "status", "error", "score", "findings"}
FINDING_KEYS = {"id", "type", "title", "severity", "method", "evidence", "fix"}
SNIPPET_MAX = 200


def _is_time(value):
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
        return True
    except (TypeError, ValueError):
        return False


def _finding_problems(f, site, where):
    problems = []
    if not isinstance(f, dict):
        return [f"{where}: finding is not an object"]
    missing = FINDING_KEYS - f.keys()
    if missing:
        problems.append(f"{where}: missing {sorted(missing)}")
    if f.get("type") not in TYPES:
        problems.append(f"{where}: bad type {f.get('type')!r}")
    if f.get("severity") not in SEVERITIES:
        problems.append(f"{where}: bad severity {f.get('severity')!r}")
    if f.get("method") not in METHODS:
        problems.append(f"{where}: bad method {f.get('method')!r}")
    if not str(f.get("id", "")).startswith(f"{site}:{f.get('type')}:") or not re.search(r":[^:]+$", str(f.get("id"))):
        problems.append(f"{where}: id {f.get('id')!r} is not <site>:<type>:<slug>")
    for key in ("title", "fix"):
        if not isinstance(f.get(key), str) or not f.get(key).strip():
            problems.append(f"{where}: {key} must be a non-empty string")
    ev = f.get("evidence")
    if not isinstance(ev, dict) or not {"where", "snippet"} <= ev.keys():
        problems.append(f"{where}: evidence needs where and snippet")
    else:
        snippet = ev.get("snippet")
        if not isinstance(ev.get("where"), str) or not isinstance(snippet, str):
            problems.append(f"{where}: evidence.where and evidence.snippet must be strings")
        else:
            if len(snippet) > SNIPPET_MAX:
                problems.append(f"{where}: snippet longer than {SNIPPET_MAX} chars")
            if key_spans(snippet) or key_spans(ev["where"]):
                problems.append(f"{where}: evidence contains an unmasked key")
    if "meta" in f and not isinstance(f["meta"], dict):
        problems.append(f"{where}: meta must be an object")
    return problems


def validate(data):
    if not isinstance(data, dict):
        return ["top level is not an object"]
    problems = []
    if not _is_time(data.get("generated_at")):
        problems.append("generated_at missing or not YYYY-MM-DDTHH:MM:SSZ")
    sites = data.get("sites")
    if not isinstance(sites, list):
        return problems + ["sites must be a list"]
    ids = set()
    for i, s in enumerate(sites):
        if not isinstance(s, dict):
            problems.append(f"sites[{i}] is not an object")
            continue
        name = s.get("site") or f"sites[{i}]"
        missing = SITE_KEYS - s.keys()
        if missing:
            problems.append(f"{name}: missing {sorted(missing)}")
        if not isinstance(s.get("site"), str) or not s.get("site").strip():
            problems.append(f"{name}: site must be a non-empty string")
        if isinstance(s.get("final_url"), str) and key_spans(s["final_url"]):
            problems.append(f"{name}: final_url contains an unmasked key")
        findings = s.get("findings")
        if not isinstance(findings, list):
            problems.append(f"{name}: findings must be a list")
            continue
        score = s.get("score")
        if s.get("error"):
            if score is not None:
                problems.append(f"{name}: score must be null when error is set")
        elif not isinstance(score, int) or isinstance(score, bool) or not 0 <= score <= 100:
            problems.append(f"{name}: score {score!r} is not an integer 0-100")
        elif score != compute_score([f for f in findings if isinstance(f, dict)]):
            expected = compute_score([f for f in findings if isinstance(f, dict)])
            problems.append(f"{name}: score {score} doesn't match the formula ({expected})")
        for j, f in enumerate(findings):
            problems += _finding_problems(f, name, f"{name} findings[{j}]")
            fid = f.get("id") if isinstance(f, dict) else None
            if fid in ids:
                problems.append(f"{name} findings[{j}]: duplicate id {fid!r}")
            ids.add(fid)
    return problems


def main(argv=None):
    path = (argv or sys.argv[1:] or ["out/findings.json"])[0]
    problems = validate(json.loads(open(path, encoding="utf-8").read()))
    for p in problems:
        print(p)
    print(f"{path}: {'OK' if not problems else f'{len(problems)} problem(s)'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
