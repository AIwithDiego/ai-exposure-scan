# Credits

Devin bills for the time it spends working. Credits burn on vague tasks, on decisions the agent has to make itself, on retry loops, and on work nobody asked for. Every prompt in `prompts/` is written to remove those four. Your job is to keep it that way.

## Before a session

- **Paste the prompt as-is.** Each one already tells the agent which files to read, which files it owns, what done looks like and when to stop.
- **Set a credit (ACU) limit on the session** if the org settings allow it. A part should take one focused session, not an afternoon.
- **Read the plan before it builds.** Devin shows a plan first. If it touches files outside its lane, or adds a library not in `docs/brief.md`, correct it in one line before it starts.

## During a session

- **Don't chat.** Every message restarts work. Batch your feedback into one message.
- **Stuck twice, stop.** Every prompt tells the agent to stop and report after two failed attempts at the same thing. If it loops anyway, stop the session and fix it by hand or rewrite the ask.
- **Small fixes by hand.** A typo, a colour, a renamed field: do it yourself in the editor. It costs nothing.
- **Never say "make it better", "improve", "clean up" or "add tests" without naming exactly what.** Open-ended asks are the most expensive thing you can type.

## Between sessions

- **One prompt = one session = one PR.** Start a new session for the next prompt instead of continuing a long one; long sessions carry context that costs every step.
- **Merge before the next session starts** so the agent reads the current `main`, not an old branch.
- **No live-site scans in loops.** Agents test against `fixtures/` and saved raw files. Live sites only in `05` and `06`, a handful of times.

## If credits run low

Drop in this order: country map (already out of scope), policy reader model path (keyword fallback is fine), extra demo sites, `agent_ready` checks. Never drop: fetcher, chatbot + key detection, dashboard drilldown with evidence.
