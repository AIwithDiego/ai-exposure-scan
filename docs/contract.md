# Contract

The two formats every part agrees on. If you need to change one, tell the team first and update this file in the same PR. Everything else is yours to decide inside your part.

## 1. `out/raw/<site>.json` (Fetcher writes, Detectors + Policy reader read)

One file per site. `<site>` is the bare domain, e.g. `example.ie`.

```json
{
  "site": "example.ie",
  "url": "https://example.ie/",
  "final_url": "https://www.example.ie/",
  "fetched_at": "2026-11-07T12:00:00Z",
  "status": 200,
  "error": null,
  "html": "<!doctype html>... (rendered DOM after load, capped at 2 MB)",
  "page_text": "visible text of the page, capped at 200 KB",
  "scripts": [
    {
      "src": "https://widget.intercom.io/widget/abc123",
      "inline": false,
      "content": "script body as loaded, capped at 2 MB, or null if not captured"
    },
    {
      "src": null,
      "inline": true,
      "content": "window.intercomSettings = {...}"
    }
  ],
  "requests": [
    { "url": "https://api-iam.intercom.io/messenger/web/ping", "domain": "api-iam.intercom.io", "method": "POST", "resource_type": "xhr" }
  ],
  "robots_txt": "User-agent: GPTBot\nDisallow: /\n... or null if 404",
  "llms_txt": "contents or null if 404",
  "privacy_policy": {
    "url": "https://www.example.ie/privacy",
    "text": "visible text, capped at 200 KB"
  }
}
```

Rules:
- `privacy_policy` is `null` if no link containing "privacy" (or "privacidad", "datenschutz", "confidentialité") is found on the homepage.
- `error` is a short string if the page failed to load; the other fields are then best effort, never missing (use `null` or `[]`).
- Wait for network idle or 10 seconds, whichever comes first, then capture. Many chat widgets load late.

## 2. `out/findings.json` (Detectors + Policy reader write, Dashboard reads)

```json
{
  "generated_at": "2026-11-07T12:05:00Z",
  "sites": [
    {
      "site": "example.ie",
      "final_url": "https://www.example.ie/",
      "status": 200,
      "error": null,
      "score": 62,
      "findings": [ { "...": "Finding, see below" } ]
    }
  ]
}
```

Optional site field `label`: a display name from a `data/sites.txt` line like `http://localhost:8765/ | Bella's Café (demo)`. The fetcher stores it as `label` in the raw file and it is carried to the site entry; the dashboard shows `label || site`. `site` and `id` never change.

### Finding

```json
{
  "id": "example.ie:chatbot:intercom",
  "type": "chatbot",
  "title": "Intercom chat widget on the homepage",
  "severity": "info",
  "method": "detected",
  "evidence": {
    "where": "https://widget.intercom.io/widget/abc123",
    "snippet": "<script src=\"https://widget.intercom.io/widget/abc123\">"
  },
  "fix": "Plain-English sentence for the owner: what to tell your web person.",
  "meta": { "vendor": "Intercom", "country": "US", "eu": false }
}
```

| Field | Values |
|---|---|
| `type` | `chatbot` · `data_transfer` · `key_leak` · `disclosure` · `agent_ready` |
| `severity` | `high` · `medium` · `low` · `info` |
| `method` | `detected` (plain code) · `judged` (model or heuristic) |
| `evidence.where` | URL of the script, page, `robots.txt`, `llms.txt` or policy |
| `evidence.snippet` | exact text, max 200 chars, keys masked |
| `fix` | one or two plain sentences, no jargon |
| `meta` | free-form object for extras (vendor, country, eu, crawler, key_type...). Optional. |

`id` is `<site>:<type>:<short-slug>` and must be unique and stable across runs.

### Severity guide

| Finding | Severity |
|---|---|
| Live-looking AI key (OpenAI, Anthropic, Groq, HF, Replicate) in public JS | `high` |
| Google `AIza` key in public JS | `low` (usually a Maps key, meant to be public; say so) |
| Chatbot from a vendor likely outside the EU, policy doesn't name it | `medium` |
| Chatbot present, no AI disclosure found | `medium` |
| Privacy policy doesn't name an AI provider that's on the page | `medium` |
| Chatbot / vendor present (the fact itself) | `info` |
| Data likely leaves the EU (vendor outside EU) | `low` |
| No `llms.txt`, no AI crawler rules, MCP named | `info` |

### Score

`score = max(0, 100 - 25*high - 10*medium - 3*low)`. `info` doesn't count. `score` is `null` when the site failed to load (`error` set); the dashboard shows "Couldn't scan". Computed by whichever step writes `findings.json` last (the `all` command).

## 3. Merging rule

Detectors and Policy reader both produce findings. Detectors write `out/findings.json` first; Policy reader reads it, appends its findings to each site, recomputes the score and writes it back. Running `policy` twice must not duplicate findings (dedupe by `id`).
