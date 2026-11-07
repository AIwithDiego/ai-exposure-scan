# AI Exposure Scan

Type in a website. A headless browser visits it like a normal person would. We collect what it loads, run checks, and show what AI the site exposes, with the evidence for every finding.

> TrendAI scans enterprises for exposed AI. We built the version for the café down the road.

Built at the Cognition x Give(a)Go build day, Dublin, 7 Nov 2026.

![How AI Exposure Scan works](docs/how-it-works.svg)

## What it finds

| Type | What we look for |
|---|---|
| `chatbot` | AI chat widgets on the site (Intercom, Tidio, Voiceflow, Botpress, Chatbase, GPT embeds...) and who the vendor is |
| `data_transfer` | Where that data likely goes: vendor country, inside or outside the EU |
| `key_leak` | AI API keys sitting in public JavaScript (masked, never tested) |
| `disclosure` | Does the site tell people they are talking to AI (EU AI Act Art. 50)? Does the privacy policy name its AI providers? |
| `agent_ready` | `llms.txt`, AI crawler rules in `robots.txt`, MCP endpoints the site names |

Every finding carries its evidence (which script, which line, which sentence of the policy). Anything a model decided is labelled `judged`; everything else is `detected` by plain code.

## How the pipeline works

```
sites.txt ──> Fetcher ──> out/raw/<site>.json ──> Detectors ─┐
                                              └─> Policy reader ─┴─> out/findings.json ──> Dashboard
```

1. **Fetcher** (`scan/fetcher.py`): Playwright opens each site once, like a visitor. Saves HTML, scripts, network calls, `robots.txt`, `llms.txt`, privacy policy text.
2. **Detectors** (`scan/detectors.py`): plain code. Vendor list, key patterns, country table, crawler rules.
3. **Policy reader** (`scan/policy.py`): the only model part. Reads the privacy policy and widget text.
4. **Dashboard** (`dashboard/`): overview of all sites plus a drilldown per site with evidence and "what to tell your web person".

## Start here

You are on the team (or you are the whole team). Do this:

1. **Read [`docs/brief.md`](docs/brief.md)** (5 minutes). The idea, the rules, the stack. Nothing to decide, it is decided.
2. **Read [`docs/contract.md`](docs/contract.md)**. The two JSON formats every part agrees on. This is what lets us build in parallel.
3. **Pick your lane in [`docs/team-plan.md`](docs/team-plan.md)** by team size (1, 2, 3 or 4 people).
4. **Open the prompt for your lane in [`prompts/`](prompts/)** and paste it into Devin (or Claude Code, Cursor, Codex, whatever you use). Each prompt is self-contained and points the agent at this repo.
5. **Read [`docs/credits.md`](docs/credits.md)** before your first session. Credits are the scarce thing today.

## Repo map

```
docs/
  brief.md          the idea, who it's for, the rules, the stack
  contract.md       raw.json and findings.json formats (the agreement between parts)
  team-plan.md      who does what, for 1 to 4 people, and the order of work
  credits.md        how to not burn Devin credits
  pitch.md          the demo script
  how-it-works.svg  the one-picture explainer (use it in the pitch)
prompts/
  01-fetcher.md         Fetcher
  02-detectors.md       Detectors
  03-policy-reader.md   Policy reader
  04-dashboard.md       Dashboard
  05-connect.md         wire everything end to end
  06-demo-polish.md     make one demo site perfect
data/
  chatbot-vendors.json  vendor signatures + country + EU flag
  key-patterns.json     AI key regexes (masking rules included)
  ai-crawlers.json      AI crawler user agents for robots.txt checks
  fake-findings.json    fake output so the dashboard can start at minute one
  sites.txt             the demo site list
fixtures/
  cafe-demo/            a fake café website with known findings, for a demo that never fails
```

## Dashboard

Needs Node 18+.

```
cd dashboard
npm install
npm run dev        # http://localhost:5173
npm run build      # production build in dashboard/dist
```

It reads `dashboard/public/findings.json`, which starts as a copy of `data/fake-findings.json`. After a scan, `npm run data` copies `../out/findings.json` there (`npm run data:fake` puts the fake data back). Any file in the contract format works without code changes.

## Ground rules

- **Passive only.** One normal page load plus `robots.txt`, `llms.txt` and the privacy policy. No crawling, no form posts, no talking to the bot, no probing paths.
- **Keys are masked and never tested.** We show `sk-proj-AbCd…wxyz`, never the full key, and never call an API with it.
- **Demo on our own sites, volunteers' sites, or the fixture.** We do not publish results about third parties.

MIT licence.

## Run

Python 3.11+.

```
pip install -r requirements.txt
playwright install chromium
```

Scan the fixture: start it in one terminal with `python -m http.server 8765 --directory fixtures/cafe-demo`, then in another:

```
python -m scan fetch --sites data/sites.txt   # writes out/raw/<site>.json
python -m scan all --sites data/sites.txt     # fetch, then detect and policy once they exist
pytest
```
