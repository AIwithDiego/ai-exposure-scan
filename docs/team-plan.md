# Team plan

The contract in `docs/contract.md` is fixed, and `data/fake-findings.json` + `fixtures/cafe-demo` exist from minute one. So no part waits on another. Agents can run in parallel even if you are alone: one person can drive three Devin sessions at once.

## Step 0 (everyone, together, first 20 minutes)

1. One person creates the team repo: **Use this template** on GitHub (or fork) into an account Devin can access. Everyone works there from now on.
2. Agree the site list in `data/sites.txt`: the fixture, our own sites, volunteers who said yes. Max 10.
3. Read `docs/brief.md` and `docs/contract.md` out loud if needed. Any change to the contract happens now, never later.
4. Pick lanes below. Each person names their lane in the team chat.

## Lanes by team size

### 1 person (you + parallel agents)

| Session | Prompt | Runs |
|---|---|---|
| A | `01-fetcher.md` | first |
| B | `02-detectors.md` | at the same time as A |
| C | `04-dashboard.md` | at the same time as A and B |
| D | `03-policy-reader.md` | when A or B is merged |
| E | `05-connect.md` | when A to D are merged |
| F | `06-demo-polish.md` | last |

While agents run, you review PRs, merge, and write the pitch (`docs/pitch.md`). Three sessions at once is the sweet spot; more and you can't review fast enough.

### 2 people

| Person | Lanes |
|---|---|
| Pipeline | `01-fetcher` + `02-detectors` in parallel, then `03-policy-reader`, then `05-connect` |
| Front + pitch | `04-dashboard`, then pitch, then `06-demo-polish` |

### 3 people

| Person | Lanes |
|---|---|
| Fetch | `01-fetcher`, then `05-connect` |
| Checks | `02-detectors`, then `03-policy-reader` |
| Front + pitch | `04-dashboard`, then `06-demo-polish`, owns the pitch |

### 4 people

| Person | Lanes |
|---|---|
| Fetch | `01-fetcher`, then `05-connect` |
| Detect | `02-detectors` |
| Policy | `03-policy-reader`, then helps on `06` |
| Front | `04-dashboard`, then `06-demo-polish` |

Whoever is presenting owns `docs/pitch.md` and the demo laptop. Presenter should not also be the last one merging.

## Order of work

1. **Build on fake data.** Fetcher runs on the fixture. Detectors and Policy run on saved raw files. Dashboard runs on `data/fake-findings.json`.
2. **Connect end to end** (`05-connect.md`): real raw → real findings → dashboard. On the fixture first, then the site list.
3. **Polish one demo site** (`06-demo-polish.md`). One flawless scan beats ten shaky ones.
4. **Freeze code one hour before demos.** After the freeze: only copy fixes and rehearsal. Run the demo three times.

## Merging

- One PR per prompt. Small PRs, merged fast.
- Whoever opens it doesn't merge it alone: a second person (or you, solo) reads the diff summary and runs the one check the prompt names.
- `main` must always run. If a merge breaks `main`, revert first, debug after.
