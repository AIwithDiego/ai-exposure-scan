import argparse
import importlib
import importlib.util
import json
import shutil
from pathlib import Path

DEFAULT_SITES = "data/sites.txt"
DEFAULT_OUT = "out"
DASHBOARD_FINDINGS = Path(__file__).resolve().parent.parent / "dashboard" / "public" / "findings.json"


def _part(name):
    """Import a pipeline part, or return None if that part isn't built yet."""
    if importlib.util.find_spec(f"scan.{name}") is None:
        return None
    return importlib.import_module(f"scan.{name}")


def cmd_fetch(args):
    fetcher = _part("fetcher")
    if fetcher is None:
        print("fetch: not implemented yet")
        return 0
    fetcher.run(args.sites, Path(args.out) / "raw")
    return 0


def cmd_detect(args):
    detectors = _part("detectors")
    if detectors is None:
        print("detect: not implemented yet")
        return 0
    detectors.run(Path(args.out) / "raw", Path(args.out) / "findings.json")
    return 0


def cmd_policy(args):
    policy = _part("policy")
    if policy is None:
        print("policy: not implemented yet")
        return 0
    policy.run(Path(args.out) / "raw", Path(args.out) / "findings.json")
    return 0


def _rescore_and_summarise(findings_path):
    if not findings_path.exists():
        return
    data = json.loads(findings_path.read_text(encoding="utf-8"))
    score = _part("score")
    if score is not None:
        for site in data.get("sites", []):
            site["score"] = score.compute_score(site.get("findings", []), site.get("error"))
        findings_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print()
    print(f"{'site':<30} {'score':>5} {'high':>5} {'medium':>7}")
    for site in data.get("sites", []):
        sev = [f.get("severity") for f in site.get("findings", [])]
        shown = "-" if site.get("score") is None else site["score"]
        print(f"{site['site']:<30} {shown:>5} {sev.count('high'):>5} {sev.count('medium'):>7}")


def _validate(findings_path):
    from scan.validate import validate

    problems = validate(json.loads(findings_path.read_text(encoding="utf-8")))
    for p in problems:
        print(f"contract: {p}")
    return problems


def _drop_stale_raw(raw_dir, sites_path):
    """Remove raw files for sites that aren't in the current site list, so they don't reach findings.json."""
    fetcher = _part("fetcher")
    if fetcher is None or not raw_dir.exists():
        return
    keep = {fetcher.raw_filename(fetcher.site_name(url)) for url in fetcher.read_sites(sites_path)}
    for path in raw_dir.glob("*.json"):
        if path.name not in keep:
            path.unlink()
            print(f"all: removed stale {path}")


def cmd_all(args):
    cmd_fetch(args)
    _drop_stale_raw(Path(args.out) / "raw", args.sites)
    cmd_detect(args)
    cmd_policy(args)
    findings_path = Path(args.out) / "findings.json"
    if not findings_path.exists():
        print("all: no findings.json written")
        return 1
    _rescore_and_summarise(findings_path)
    if _validate(findings_path):
        return 1
    if not args.no_dashboard:
        DASHBOARD_FINDINGS.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(findings_path, DASHBOARD_FINDINGS)
        print(f"\ncopied to {DASHBOARD_FINDINGS.relative_to(DASHBOARD_FINDINGS.parents[2])}")
    return 0


def cmd_serve(args):
    from scan import server

    return server.serve(args.port, args.out, args.allow_fixture)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m scan", description="AI Exposure Scan pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    commands = {
        "fetch": (cmd_fetch, "visit each site once and write out/raw/<site>.json"),
        "detect": (cmd_detect, "run plain-code checks on out/raw/*.json and write out/findings.json"),
        "policy": (cmd_policy, "read privacy policies and add disclosure findings"),
        "all": (cmd_all, "fetch, detect and policy in order, then copy findings.json to the dashboard"),
        "serve": (cmd_serve, "serve the built dashboard and a scan-one-site API (POST /api/scan)"),
    }
    for name, (func, help_text) in commands.items():
        p = sub.add_parser(name, help=help_text)
        if name == "serve":
            p.add_argument("--port", type=int, default=8000, help="port to listen on (default: 8000)")
            p.add_argument("--allow-fixture", action="store_true",
                           help="allow scanning the local fixture at localhost:8765")
        else:
            p.add_argument("--sites", default=DEFAULT_SITES, help="file with one domain or URL per line")
        p.add_argument("--out", default=DEFAULT_OUT, help="output directory (default: out)")
        if name == "all":
            p.add_argument("--no-dashboard", action="store_true",
                           help="don't copy findings.json to dashboard/public/")
        p.set_defaults(func=func)
    args = parser.parse_args(argv)
    return args.func(args)
