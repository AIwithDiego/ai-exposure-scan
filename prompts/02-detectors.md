# 02 · Detectors

Paste everything below the line into your agent. Replace `<TEAM_REPO>` with your team repo URL.

---

You are building the Detectors for **AI Exposure Scan** in the repo `<TEAM_REPO>`.

**Read first, in this order:** `docs/brief.md`, `docs/contract.md` (section 1 is your input, section 2 your output), then the data files `data/chatbot-vendors.json`, `data/key-patterns.json`, `data/ai-crawlers.json`. Do not start coding until you have read them.

**Your job:** plain-code checks (no model, no network) that read every `out/raw/*.json` and write `out/findings.json` in the contract format. All your findings use `method: "detected"`.

**You own these files (create or edit only these):**
- `scan/detectors.py`
- `scan/score.py` (the score formula from the contract, plus a `merge_findings(existing, new)` helper that dedupes by `id`)
- `tests/test_detectors.py`
- `tests/raw/cafe-demo.json` (a hand-written raw file you build from `fixtures/cafe-demo/` so you don't depend on the Fetcher)

If `scan/cli.py` doesn't exist yet, create a minimal one with a `detect` subcommand; if it exists, only add your subcommand.

**Checks to build, one function each, each returns a list of findings:**
1. `chatbots(raw)`: match every script `src`, request `domain` and inline script `content` against `data/chatbot-vendors.json` (`match` is a list of substrings). One `chatbot` finding per vendor found (severity `info`), with the first matching URL or line as evidence.
2. `data_transfer(raw, vendors_found)`: for each vendor found with `eu: false`, one `data_transfer` finding, severity `low`, title like "Chat messages likely go to the US (Intercom)". Fix text mentions the vendor's EU option if `eu_option` is true in the data file.
3. `key_leaks(raw)`: run every regex in `data/key-patterns.json` over every script `content` and the `html`. One `key_leak` finding per distinct key, severity from the data file. **Mask before anything else:** first 8 chars + `…` + last 4. The full key must never be stored, logged or printed. Snippet = 60 chars around the match with the key masked. Include `meta.key_type` and the script URL (or "inline script") as `where`.
4. `agent_ready(raw)`: 
   - `llms_txt` null → finding "No llms.txt" (info). Present → finding "Has llms.txt" (info) with the first line as snippet.
   - Parse `robots_txt` against `data/ai-crawlers.json`: one finding summarising which AI crawlers are blocked, allowed or not mentioned (info), snippet = the relevant lines.
   - MCP: only if `html`, `page_text` or `llms_txt` contains `mcp` as a word near `http` (e.g. an `https://.../mcp` URL or "MCP server"), report it (info) with the line. Never request anything.

**Output:** for each raw file, a site entry with `site`, `final_url`, `status`, `error`, `findings`, `score`. Write `out/findings.json` with `generated_at`. If `out/findings.json` exists, merge with `merge_findings` so Policy reader findings aren't lost.

**Copy:** titles under 70 chars. Fixes are one or two plain sentences an owner could forward to their web person. No jargon, no fear words. Example fix for a key: "A secret OpenAI key is visible to anyone who opens your site's code. Ask your web person to delete this key in OpenAI today and move AI calls to the server."

**Done when:**
- `python -m scan detect` on `tests/raw/cafe-demo.json` (copied to `out/raw/`) produces findings of type `chatbot`, `data_transfer`, `key_leak` and `agent_ready`.
- `pytest tests/test_detectors.py` passes and includes one test asserting no full key appears anywhere in the output JSON.

**Do not:** call any API with a key, fetch anything, add a model, touch `scan/fetcher.py` or `dashboard/`, change the contract or the data files (if a data file is wrong, say so in the PR).

**If stuck:** after two failed attempts at the same problem, stop and write what you tried in the PR description.

**Finish:** open one PR titled `Detectors` with a 5-line summary and the test output.
