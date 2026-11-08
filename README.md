# AI Exposure Scan

**Type in a website. See what AI it exposes, with the evidence.**

[![Live demo](https://img.shields.io/badge/live_demo-open-0c1a1c?style=for-the-badge&labelColor=0c1a1c&color=e3cd9c)](https://aiwithdiego.github.io/ai-exposure-scan/)
[![tests](https://img.shields.io/github/actions/workflow/status/AIwithDiego/ai-exposure-scan/tests.yml?branch=main&style=for-the-badge&label=tests&labelColor=0c1a1c)](https://github.com/AIwithDiego/ai-exposure-scan/actions/workflows/tests.yml)
![Python](https://img.shields.io/badge/Python-0c1a1c?style=for-the-badge&logo=python&logoColor=7fe6da)
![React](https://img.shields.io/badge/React-0c1a1c?style=for-the-badge&logo=react&logoColor=7fe6da)
![Playwright](https://img.shields.io/badge/Playwright-0c1a1c?style=for-the-badge&logo=playwright&logoColor=7fe6da)
[![MIT](https://img.shields.io/badge/licence-MIT-0c1a1c?style=for-the-badge&labelColor=0c1a1c)](LICENSE)

[![A fake café scores 52/100: its OpenAI key sits in public JavaScript](docs/assets/cover.png)](https://aiwithdiego.github.io/ai-exposure-scan/)

A headless browser visits the site once, like a normal visitor. Plain code checks what it loaded: chat widgets, AI keys in public JavaScript, where the data goes, whether the site says it uses AI, and how ready it is for AI agents. Every finding shows its evidence and how we know.

> TrendAI scans enterprises for exposed AI. We built the version for the café down the road.

Built in one day with [Devin](https://devin.ai) at the Cognition x Give(a)Go build day, Dublin, 7 Nov 2026.

**[Open the live demo](https://aiwithdiego.github.io/ai-exposure-scan/)** (sample data, nothing real) or [run it yourself](#run-it-yourself) and scan any site.

## What it finds

| Type | What we look for |
|---|---|
| `chatbot` | AI chat widgets on the site (104 vendors: Intercom, Tidio, Voiceflow, Botpress, Chatbase, GPT embeds...) and who the vendor is |
| `data_transfer` | Where chat data likely goes: vendor country, inside or outside the EU. Which country the site is hosted in (or which CDN edge served it), and which other outside services (analytics, ads, fonts, consent, payments...) the page contacts |
| `key_leak` | AI API keys sitting in public JavaScript (masked, never tested) |
| `disclosure` | Does the site tell people they are talking to AI (EU AI Act Art. 50)? Does the privacy policy name its AI providers? |
| `agent_ready` | `llms.txt`, AI crawler rules in `robots.txt`, MCP endpoints the site names |

Anything a model decided is labelled `judged`. Everything else is `detected` by plain code. The score is 100 minus 25 per high, 10 per medium and 3 per low finding.

<table>
<tr>
<td width="50%"><img src="docs/assets/overview.png" alt="Overview: totals per finding type and where the data likely goes"></td>
<td width="50%"><img src="docs/assets/site.png" alt="One site: score ring, each finding with its evidence and what to tell your web person"></td>
</tr>
<tr>
<td>Every site at a glance, and where its data likely goes.</td>
<td>One site: each finding, its evidence, and what to tell your web person.</td>
</tr>
</table>

## How it works

![How AI Exposure Scan works](docs/how-it-works.svg)

```
sites.txt ──> Fetcher ──> out/raw/<site>.json ──> Detectors ─┐
                                              └─> Policy reader ─┴─> out/findings.json ──> Dashboard
```

1. **Fetcher** (`scan/fetcher.py`): Playwright opens each site once, like a visitor. Saves HTML, scripts, network calls, server address, `robots.txt`, `llms.txt` and the privacy policy text.
2. **Detectors** (`scan/detectors.py`): plain code. Vendor list, key patterns, country table, offline IP-to-country lookup, crawler rules.
3. **Policy reader** (`scan/policy.py`): the only model part, and optional. Reads the privacy policy and widget text. Without an API key it falls back to keyword checks.
4. **Dashboard** (`dashboard/`): every site at a glance, plus a page per site with evidence and "what to tell your web person".

The parts only agree on two JSON formats ([`docs/contract.md`](docs/contract.md)). That is what let four parts be built in parallel on the day.

## Ground rules

- **Passive only.** One normal page load plus `robots.txt`, `llms.txt` and the privacy policy. No crawling, no form posts, no talking to the bot, no probing paths.
- **Keys are masked and never tested.** We show `sk-proj-AbCd…wxyz`, never the full key, and never call an API with it.
- **Demo on our own sites, volunteers' sites, or the fixture.** We do not publish results about third parties. The live demo is a fake café ([`fixtures/cafe-demo`](fixtures/cafe-demo)) plus made-up `.example` sites.

## Run it yourself

Python 3.11+ and Node 18+. From a fresh clone:

```
pip install -r requirements.txt
playwright install chromium
(cd dashboard && npm install)
./scripts/get-geoip.sh    # once: IP-to-country database for the hosting check
./scripts/demo.sh
```

`scripts/get-geoip.sh` downloads this month's DB-IP "IP to Country Lite" file (`dbip-country-lite-YYYY-MM.csv.gz`, about 5 MB) into `data/geoip/`. Lookups are offline; without the file the scan still runs and just skips the hosting country. `GEOIP_CSV=path/to/file.csv(.gz)` points at another file.

`scripts/demo.sh` starts the fixture on port 8765, runs `python -m scan all --sites data/sites.txt` (fetch, detect, policy, rescore, check against `docs/contract.md`, copy `out/findings.json` to `dashboard/public/findings.json`), then starts the dashboard at http://localhost:5173. The fixture server stops when you exit. `SITES=path/to/list.txt ./scripts/demo.sh` scans another list.

### Scan any website from the dashboard

```
./scripts/app.sh
```

`scripts/app.sh` checks that Python, Playwright's Chromium and ports 8765 and 8000 are ready, builds the dashboard (`npm install && npm run build`), starts the fixture on port 8765, then runs `python -m scan serve --port 8000 --allow-fixture`. Open http://localhost:8000, type a site (e.g. `example.ie`, or `localhost:8765` for the demo café) and press Scan. Each scan is one passive page load, added to `out/findings.json`. Ctrl-C stops both servers. `PYTHON=python3 ./scripts/app.sh` picks another Python.

The server refuses addresses that resolve to private, local or link-local networks; `--allow-fixture` only opens `localhost:8765`. `POST /api/scan` only accepts `Content-Type: application/json`, and refuses requests whose `Origin` is not the dashboard (`http://localhost:<port>`, `http://127.0.0.1:<port>`, or the Vite dev server at `http://localhost:5173`), so other web pages open in your browser can't start scans. One scan runs at a time (others get "try again in a moment") and each is stopped after 60 seconds. For dashboard work, run `python -m scan serve` alongside `npm run dev`; the dev server proxies `/api` to port 8000.

Check a findings file by hand with `python -m scan.validate out/findings.json`. Run the tests (fixture only, never live sites) with `pytest`.

### Dashboard only

Needs Node 18+.

```
cd dashboard
npm install
npm run dev        # http://localhost:5173
npm run build      # production build in dashboard/dist
```

It reads `dashboard/public/findings.json`. That file is git-ignored so real scan results are never committed; `npm run dev` and `npm run build` seed it from `data/fake-findings.json` if it's missing. `python -m scan all` (or `npm run data`) copies `../out/findings.json` there, and `npm run data:fake` puts the fake data back. Any file in the contract format works without code changes.

The live demo is the same dashboard built with `VITE_DEMO=1` (no scan bar, sample data only) and `BASE_PATH=/ai-exposure-scan/` for GitHub Pages. See `.github/workflows/pages.yml`.

## What went wrong

Every one of these was caught by testing on real pages, and fixed in a PR.

| | |
|---|---|
| **A map is not an AI vendor.** A Google Maps key in the page made the policy check say "your privacy policy doesn't mention Google". | [#4](https://github.com/AIwithDiego/ai-exposure-scan/pull/4) |
| **The first privacy link isn't yours.** The cookie banner links to Cookiebot's policy, and we read it as the site's. HubSpot's tracking script also passed for a chat widget. | [#9](https://github.com/AIwithDiego/ai-exposure-scan/pull/9) |
| **A local server is still a server.** Any web page open in your browser could have told the scan server to start scans. It now checks where requests come from. | [#10](https://github.com/AIwithDiego/ai-exposure-scan/pull/10) |
| **An IP address isn't a place.** A site on Vercel came out as "hosted in the US". It was served from Dublin; the address belongs to a network that answers everywhere. | [#11](https://github.com/AIwithDiego/ai-exposure-scan/pull/11) |
| **Mentioning a vendor isn't using it.** A blog post that named three AI chat companies produced three chatbots. Vendor names now only count in scripts the page actually loads. | [#12](https://github.com/AIwithDiego/ai-exposure-scan/pull/12) |

## How it was built

One day, one repo, [Devin](https://devin.ai) doing the building. The prep pack came first: a brief, a data contract, and one self-contained prompt per part. Every change then landed as a reviewed PR ([#1 to #12](https://github.com/AIwithDiego/ai-exposure-scan/pulls?q=is%3Apr)), tested against the fixture and a handful of real sites before merging.

- [`docs/brief.md`](docs/brief.md): the idea, who it's for, the rules, the stack
- [`docs/contract.md`](docs/contract.md): the two JSON formats every part agrees on
- [`docs/team-plan.md`](docs/team-plan.md): who does what, for 1 to 4 people
- [`prompts/`](prompts/): the prompt for each part, ready to paste into Devin, Claude Code, Cursor or Codex
- [`docs/credits.md`](docs/credits.md): how not to burn Devin credits
- [`docs/design-system.html`](docs/design-system.html): the dashboard's design system

### Repo map

```
scan/               the pipeline: fetcher, detectors, policy reader, score, scan server
dashboard/          React + Vite dashboard
scripts/            demo.sh, app.sh, get-geoip.sh
tests/              pytest, fixtures only
.github/workflows/  tests on every PR; the live demo deploys on merge to main
docs/
  brief.md          the idea, who it's for, the rules, the stack
  contract.md       raw.json and findings.json formats (the agreement between parts)
  team-plan.md      who does what, for 1 to 4 people, and the order of work
  credits.md        how to not burn Devin credits
  pitch.md          the demo script
  how-it-works.svg  the one-picture explainer (use it in the pitch)
  assets/           README screenshots and cover
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
  demo-findings.json    sample data for the live demo (the fixture café + made-up sites)
  services.json         other third-party services (analytics, ads, fonts...) + country + EU flag
  sites.txt             the demo site list
  geoip/                DB-IP country database, downloaded by scripts/get-geoip.sh (git-ignored)
fixtures/
  cafe-demo/            a fake café website with known findings, for a demo that never fails
  cookiebot-*/          regression fixtures for the consent-banner privacy link
```

## Credits

MIT licence. IP geolocation by [DB-IP](https://db-ip.com), licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Fonts: Titillium Web and Noto Sans Mono (SIL OFL).

Made by [Diego Bauer](https://github.com/AIwithDiego) · [aiwithdiego.com](https://www.aiwithdiego.com)
