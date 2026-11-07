# Fixture: Bella's Café

A fake site with every finding type planted, so tests and the demo never depend on a live site.

Serve it: `python -m http.server 8765 --directory fixtures/cafe-demo` then scan `http://localhost:8765/`.

| Planted | Where | Expected finding |
|---|---|---|
| Intercom config | inline script in `index.html` | `chatbot` Intercom (info) |
| Intercom is a US vendor | `data/chatbot-vendors.json` | `data_transfer` US (low) |
| Fake OpenAI key | `js/menu-assistant.js` | `key_leak` OpenAI (high), masked |
| Greeting "Hi! I'm Bella" never says it's AI | inline script | `disclosure` bot not disclosed (medium) |
| Policy names Intercom but not OpenAI | `privacy.html` | `disclosure` OpenAI not named (medium) |
| GPTBot and CCBot blocked | `robots.txt` | `agent_ready` crawler rules (info) |
| llms.txt with MCP line | `llms.txt` | `agent_ready` has llms.txt + MCP named (info) |

The key is fake and does not work. The OpenAI call in the script only runs if someone clicks the button; the scanner never clicks.
