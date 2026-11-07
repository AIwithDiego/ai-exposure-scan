# 03 · Policy reader

Paste everything below the line into your agent. Replace `<TEAM_REPO>` with your team repo URL.

---

You are building the Policy reader for **AI Exposure Scan** in the repo `<TEAM_REPO>`.

**Read first, in this order:** `docs/brief.md`, `docs/contract.md` (all of it, including the merging rule in section 3), `data/chatbot-vendors.json`.

**Your job:** the only part that may use a model. It reads each site's privacy policy text and page text from `out/raw/*.json`, plus the vendors already found in `out/findings.json`, and adds `disclosure` findings. Every finding you write has `method: "judged"`.

**You own these files (create or edit only these):**
- `scan/policy.py`
- `tests/test_policy.py`

Add a `policy` subcommand to `scan/cli.py` (only that). Use `merge_findings` and the score function from `scan/score.py` if they exist; if they don't yet, write minimal local versions and leave a `# TODO: use scan/score.py` note.

**Two questions per site:**
1. **Does the site tell people the bot is AI?** Only asked if a `chatbot` finding exists for the site. Look at `page_text` and inline script content for widget greeting or config text (e.g. `"greeting"`, `"welcomeMessage"`, `"botName"`). Answer `yes` / `no` / `unknown`. `unknown` when no greeting text is visible in what we captured (we never open the widget). `no` and `unknown` → finding, severity `medium` for `no`, `low` for `unknown`, title says which.
2. **Does the privacy policy name the AI providers on the page?** For each vendor from the `chatbot` findings, plus OpenAI / Anthropic / Google if a key or AI request was found: is it named in `privacy_policy.text`? Also: does the policy mention AI, chatbot, automated processing or similar at all? Missing vendor → `medium` finding per vendor. No policy at all → one `medium` finding "No privacy policy found on the homepage".

**Two engines, same output:**
- **Model path:** if `ANTHROPIC_API_KEY` is set use the Anthropic SDK with a small, fast model; else if `OPENAI_API_KEY` is set use OpenAI. Send only the relevant text (policy capped at 30 KB, greeting snippets). Ask for strict JSON: `{answer, quote}` where `quote` is the exact sentence from the text that supports the answer (or empty). Use `quote` as `evidence.snippet`. If the quote isn't actually in the text, discard it and fall back to the keyword path for that question.
- **Keyword path** (no key, or model error): case-insensitive search for vendor names and the words `artificial intelligence`, `AI`, `chatbot`, `virtual assistant`, `automated`, `inteligencia artificial`. Evidence = the sentence containing the match.
- Put `meta.engine` = `"model"` or `"keywords"` on each finding.

**Done when:**
- With no API key set, `python -m scan policy` on the fixture raw file adds at least one `disclosure` finding, writes it into `out/findings.json` without duplicating on a second run, and recomputes scores.
- `pytest tests/test_policy.py` passes using the keyword path only (no network in tests).

**Do not:** fetch anything, send full HTML to a model, put API keys in code or logs, touch other parts, change the contract.

**If stuck:** after two failed attempts at the same problem, stop and write what you tried in the PR description.

**Finish:** open one PR titled `Policy reader` with a 5-line summary and the test output.
