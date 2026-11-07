# Brief

Read this first. Every agent session starts by reading this file and `docs/contract.md`.

## The idea

Small businesses add AI to their websites without knowing it: a chat widget the web person installed, a plugin that calls OpenAI, a key pasted into a script. Big companies pay for outside-in AI exposure scans. A café, a dentist or a local shop has nothing.

**AI Exposure Scan** takes a list of domains, visits each one like a normal visitor, and shows:

1. **AI on the site:** which chatbot or AI widget is loaded, and the vendor.
2. **Where data goes:** that vendor's country, and whether the data likely leaves the EU.
3. **Leaked AI keys:** API keys visible in public JavaScript. Masked. Never tested.
4. **Disclosure:** does the site say the bot is AI (EU AI Act Art. 50)? Does the privacy policy name its AI providers?
5. **Agent readiness:** `llms.txt`, AI crawler rules in `robots.txt`, MCP endpoints the site itself names.

Each finding comes with its evidence and a plain-English fix: "what to tell your web person".

## Who it's for

The owner of a small business who is not technical. They should understand every finding without knowing what JavaScript is. The judges should see a working scan of a real site in under a minute.

## What "done" looks like

- `python -m scan all --sites data/sites.txt` runs the whole pipeline and writes `out/findings.json`.
- The dashboard shows an overview of all scanned sites (score, counts by finding type, where data goes by country) and a drilldown per site with each finding's evidence and fix.
- The `fixtures/cafe-demo` site produces at least one finding of every type, every time.
- One real site (ours or a volunteer's) scans cleanly live during the demo.

## The rules (non-negotiable)

1. **Passive only.** Per site: one page load in a headless browser, plus `GET /robots.txt`, `GET /llms.txt`, and the privacy policy page if linked from the homepage. That's it. No crawling, no guessing paths, no submitting forms, no opening or talking to the chatbot.
2. **Keys are masked at the source.** The fetcher stores script content as-is, but every key that leaves the detectors is masked: first 8 characters + `…` + last 4. Never print, log or display a full key. Never call any API with a found key.
3. **Evidence or it didn't happen.** Every finding has `evidence.where` (URL, script, or file) and `evidence.snippet` (the exact text, max 200 chars, keys masked).
4. **Label the method.** `detected` = plain code matched it. `judged` = a model or heuristic decided it. Nothing judged is presented as fact.
5. **Country is "likely".** We know the vendor's headquarters, not where a given customer's data is hosted. Say "likely leaves the EU", never "leaves the EU".
6. **MCP only when named.** Report an MCP endpoint only if the page or `llms.txt` mentions it. Never probe `/mcp` or similar paths.

## The stack (decided, don't revisit)

| Part | Choice |
|---|---|
| Language (pipeline) | Python 3.11+ |
| Browser | Playwright for Python, Chromium, headless |
| Package layout | `scan/` package: `fetcher.py`, `detectors.py`, `policy.py`, `cli.py`, `__main__.py` |
| Dependencies | `requirements.txt` (playwright, httpx if needed, anthropic or openai only in policy.py). No frameworks. |
| CLI | `python -m scan fetch|detect|policy|all --sites data/sites.txt` |
| Output | `out/raw/<site>.json`, `out/findings.json` |
| Dashboard | React + Vite, plain JavaScript, no UI library, one CSS file. Reads `dashboard/public/findings.json`. |
| Tests | `pytest`, only against `fixtures/` and saved raw files. No live sites in tests. |
| Model (policy reader) | Read key from env `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`. If neither is set, fall back to the keyword heuristic. Both paths output `method: "judged"`. |

## Out of scope

Login, accounts, a database, deploying anywhere, a crawler, a world map (a country list is enough; map only if everything else is done), scanning more than about 10 sites, PDF reports, emailing results.

## Tone of the copy (dashboard + fixes)

Plain, calm, specific. No fear-mongering. "Your chat widget is from Intercom, a US company. Customer messages likely leave the EU unless EU hosting is switched on. Ask your web person to check." Never "CRITICAL VULNERABILITY".
