# 01 · Fetcher

Paste everything below the line into your agent. Replace `<TEAM_REPO>` with your team repo URL.

---

You are building the Fetcher for **AI Exposure Scan** in the repo `<TEAM_REPO>`.

**Read first, in this order:** `docs/brief.md`, `docs/contract.md` (section 1 is your output format). Do not start coding until you have read both.

**Your job:** a Python module that takes a list of domains and, for each one, visits it once in headless Chromium like a normal visitor and writes `out/raw/<site>.json` exactly in the contract format.

**You own these files (create or edit only these):**
- `scan/__init__.py`, `scan/__main__.py`, `scan/cli.py` (CLI skeleton: `fetch`, `detect`, `policy`, `all` subcommands; only `fetch` is implemented by you, the others print "not implemented yet" and exit 0)
- `scan/fetcher.py`
- `requirements.txt` (add `playwright`, `pytest`; nothing else unless strictly needed)
- `tests/test_fetcher.py`
- `.gitignore` (add `out/`, `node_modules/`, `__pycache__/`, `.venv/`)

**Build:**
1. `python -m scan fetch --sites data/sites.txt` reads one domain or URL per line (skip blanks and `#` comments). Bare domains get `https://`. A `http://localhost...` line is kept as-is (used for the fixture).
2. Per site, with Playwright (Chromium, headless, a normal desktop user agent, 1280x800):
   - Listen to `page.on("response")` before navigating. For every response of resource type `script`, store `src` and the body text (cap 2 MB, ignore failures). Record every request in `requests` (url, domain, method, resource_type).
   - `page.goto(url)`, then wait for network idle or 10 s, whichever first.
   - Capture `final_url`, `status`, rendered `html` (`page.content()`, cap 2 MB), `page_text` (`document.body.innerText`, cap 200 KB).
   - Inline scripts: collect every `<script>` without `src` from the DOM, `inline: true`.
   - Find the privacy policy link: first `<a>` whose text or href contains `privacy`, `privacidad`, `datenschutz` or `confidentialit` (case-insensitive). If found, open it in the same browser context, capture its visible text (cap 200 KB). Else `null`.
   - `GET /robots.txt` and `GET /llms.txt` on the final origin (use the context's `request` API). Store body if status 200 and content isn't HTML, else `null`.
3. Never crash the batch: wrap each site; on failure write the file with `error` set and safe defaults.
4. Total per site: one page load, plus robots, llms and privacy. Nothing else. No crawling, no other paths.
5. Print one line per site: `example.ie  200  42 scripts  privacy: yes  llms: no`.

**Done when:**
- `python -m http.server 8765 --directory fixtures/cafe-demo` + a sites file containing `http://localhost:8765/` produces `out/raw/localhost_8765.json` (sanitise `:` to `_` in filenames) where `scripts` includes the fake chat widget and the inline config, `privacy_policy.text` is non-empty and `llms_txt` is non-null.
- `pytest tests/test_fetcher.py` passes. The test starts that local server itself (use a fixture with `subprocess` or `http.server` in a thread) and asserts the three things above. No live internet in tests.
- `playwright install chromium` is the only setup step beyond `pip install -r requirements.txt`; write both in a short "Run" section appended to `README.md`.

**Do not:** add detectors, touch `dashboard/`, add async frameworks, add retries beyond one, add a crawler, change the contract.

**If stuck:** after two failed attempts at the same problem, stop and write what you tried and what failed in the PR description. Do not keep retrying.

**Finish:** open one PR titled `Fetcher` with a 5-line summary and the test output.
