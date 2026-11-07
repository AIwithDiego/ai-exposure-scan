# Pitch (3 minutes)

The presenter owns this file. Rewrite it in your own words; keep the structure.

## 1. The problem (30 s)

Every small business website now has AI on it. A chat widget the web person added. A plugin that calls OpenAI. Sometimes a secret key pasted straight into the page.

The owner usually doesn't know. Big companies pay for scans that find this. The café down the road has nothing.

> TrendAI scans enterprises for exposed AI. We built the version for the café down the road.

## 2. Live demo (90 s)

1. Terminal: `python -m scan all --sites data/sites.txt`. Say: "One visit per site, like a normal visitor. Nothing hacked, nothing tested."
2. Dashboard overview: scores, counts, where the data likely goes.
3. Click **Bella's Café** (the fixture):
   - Chat widget from a US vendor, messages likely leave the EU.
   - A secret OpenAI key in the page code. Masked. "Anyone could spend their credit."
   - The bot never says it's AI: EU AI Act transparency rule.
   - Every finding shows its evidence, and the sentence to forward to your web person.
4. Click the live site. Show what's real.

## 3. How it works (30 s)

Headless browser loads the page once. Plain-code checks for widgets, keys and crawler rules. One model step reads the privacy policy, and anything a model decided is labelled "judged". Built today with Devin, in parallel lanes against one agreed data format.

## 4. What's next (30 s)

- Run it as an MCP tool, so any AI assistant can check a site.
- A monthly scan for a list of local businesses, with the fix written for them.

## Demo checklist

- [ ] Fixture server running (`make demo` does it)
- [ ] Live site scanned once in the last hour, result looks right
- [ ] Browser zoom 125 %, notifications off
- [ ] Backup: screenshots of both site views in case the Wi-Fi dies
