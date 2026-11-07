# 06 · Demo polish

Run this last, after `05` is merged. Paste everything below the line into your agent. Replace `<TEAM_REPO>` with your team repo URL and `<DEMO_SITE>` with the one real site we demo live.

---

You are polishing **AI Exposure Scan** for a 3-minute live demo, in the repo `<TEAM_REPO>`.

**Read first:** `docs/brief.md`, `docs/pitch.md`, then run `make demo` (or `scripts/demo.sh`) once and look at every screen.

**The demo:** we scan `fixtures/cafe-demo` (guaranteed findings of every type) and `<DEMO_SITE>` live. The audience is non-technical judges. They should understand each finding in five seconds.

**Fix only these, in this order, and stop when time runs out:**
1. Any crash, blank screen, console error or broken layout at 1280 px and 375 px.
2. Any finding on the two demo sites whose title or fix is unclear, too technical, or sounds alarmist. Rewrite the copy in the code that generates it (detectors / policy), not in the JSON.
3. A one-line explainer under the overview header: "We visited each site once, like a normal visitor, and listed the AI it exposes. Nothing was hacked or tested."
4. If everything above is done: on the site view, a small "How we know" line under each evidence block ("Found in a script loaded from widget.intercom.io").

**Do not:** add a "Scan" input to the dashboard (the demo runs the CLI, then refreshes the page), add features, new checks, new pages, libraries, or change the contract. No more than three full scans of `<DEMO_SITE>`.

**If stuck:** after two failed attempts at the same problem, stop and write what you tried in the PR description.

**Finish:** one PR titled `Demo polish` with before/after screenshots of the site view.
