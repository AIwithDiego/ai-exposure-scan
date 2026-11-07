# 05 · Connect end to end

Run this only after Fetcher, Detectors, Policy reader and Dashboard are merged into `main`. Paste everything below the line into your agent. Replace `<TEAM_REPO>` with your team repo URL.

---

You are wiring the parts of **AI Exposure Scan** together in the repo `<TEAM_REPO>`. The four parts already exist on `main`.

**Read first:** `docs/brief.md`, `docs/contract.md`, then skim `scan/` and `dashboard/src/` to see what's there. Do not rewrite working parts.

**Your job:** make one command take a site list all the way to the dashboard, and fix only the seams between parts.

**Build:**
1. `python -m scan all --sites data/sites.txt` runs fetch → detect → policy in order, recomputes scores, writes `out/findings.json`, then copies it to `dashboard/public/findings.json`. Print a final summary table: site, score, high, medium.
2. `make demo` (or `scripts/demo.sh` if `make` is awkward): starts the fixture server on port 8765, runs `scan all` on `data/sites.txt`, then starts the dashboard dev server. Stops the fixture server on exit.
3. Run it on the fixture alone first. Then on the full `data/sites.txt` once. Fix only mismatches against the contract (wrong field names, missing defaults, crashes on `null`).
4. Add `tests/test_end_to_end.py`: fixture server → `scan all` → assert `findings.json` validates against the contract (write a small validator in `scan/validate.py`) and has at least one finding of each of the five types for the fixture site.

**You may edit:** `scan/cli.py`, `scan/validate.py`, `Makefile` or `scripts/demo.sh`, `tests/test_end_to_end.py`, and small fixes anywhere else where a part breaks the contract. List every such fix in the PR.

**Done when:** `make demo` (or the script) works from a fresh clone after `pip install -r requirements.txt && playwright install chromium && (cd dashboard && npm install)`, the end-to-end test passes, and the "Run" section of `README.md` describes exactly those steps.

**Do not:** add features, restyle the dashboard, refactor working code, scan the site list more than twice.

**If stuck:** after two failed attempts at the same problem, stop and write what you tried in the PR description.

**Finish:** open one PR titled `Connect end to end` with the summary table from the real run.
