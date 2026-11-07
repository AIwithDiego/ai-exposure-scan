# 04 · Dashboard

Paste everything below the line into your agent. Replace `<TEAM_REPO>` with your team repo URL.

---

You are building the Dashboard for **AI Exposure Scan** in the repo `<TEAM_REPO>`.

**Read first, in this order:** `docs/brief.md` (especially "Who it's for" and "Tone of the copy"), `docs/contract.md` section 2, `data/fake-findings.json`.

**Your job:** a single-page React app that reads `findings.json` and makes it obvious to a non-technical business owner what AI their site exposes and what to do about it. Start on `data/fake-findings.json`; the real file has the same shape.

**You own everything inside `dashboard/`.** Touch nothing outside it.

**Stack (decided):** Vite + React, plain JavaScript, no UI library, no router, no state library, one `src/styles.css`. Data loaded with `fetch("/findings.json")` from `dashboard/public/findings.json`. Add an npm script `"data": "cp ../out/findings.json public/findings.json"`; until real data exists, copy `../data/fake-findings.json` there.

**Screens:**
1. **Overview** (default):
   - Header: "AI Exposure Scan", generated time, number of sites.
   - Totals row: count of findings by type (chatbot, data transfer, key leak, disclosure, agent ready), each a small card.
   - "Where the data likely goes": a simple list or bar per country from `data_transfer` findings' `meta.country`, with EU vs outside EU. No map.
   - Sites table: site, score (0 to 100 with a colour band: 80+ green, 50 to 79 amber, below 50 red), count of high / medium findings, one-line worst finding. Click a row → site view.
2. **Site view** (same page, state toggle, Back button):
   - Site name, final URL, score, error banner if `error`.
   - Findings grouped by type, sorted high → info. Each finding card: title, severity pill, method badge (`detected` solid, `judged` outlined with tooltip "A model or rule decided this; check it"), evidence (`where` as a link, `snippet` in monospace), and the fix in a box labelled **What to tell your web person** with a Copy button.
   - Empty state per type: "Nothing found" in muted text.

**Design:** calm and readable, not a hacker console. Light background, one accent colour, system font stack, generous spacing, 16 px base. Works at 375 px wide (cards stack, table becomes cards). Severity colours: high red, medium amber, low blue, info grey. Text contrast at least 4.5:1.

**Done when:**
- `cd dashboard && npm install && npm run dev` shows both screens with the fake data, no console errors.
- `npm run build` succeeds.
- Swapping `public/findings.json` for any file in the contract format needs no code change.
- Append a "Dashboard" run section to `README.md` (that one section only).

**Do not:** add a backend, charts library, map, auth, dark mode toggle, animations beyond simple hover, or change the data shape.

**If stuck:** after two failed attempts at the same problem, stop and write what you tried in the PR description.

**Finish:** open one PR titled `Dashboard` with a 5-line summary and a screenshot of each screen.
