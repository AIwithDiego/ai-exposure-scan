"""Policy reader: adds `disclosure` findings (method "judged") to out/findings.json.

Two questions per site: does the chat say it's AI, and does the privacy policy name the AI
providers on the page. Uses a small model if ANTHROPIC_API_KEY or OPENAI_API_KEY is set, else a
keyword heuristic. Never fetches anything and never sends full HTML to a model.
"""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from scan.detectors import VENDORS, clip, mask_all_keys, page_url, short_name, slugify
from scan.score import compute_score, merge_findings

POLICY_MAX = 30_000
SNIPPET_MAX = 200
ANTHROPIC_MODEL = "claude-haiku-5-5"
OPENAI_MODEL = "gpt-4o-mini"

AI_TERMS = ["artificial intelligence", "AI", "chatbot", "virtual assistant", "automated",
            "inteligencia artificial"]
AI_RE = re.compile(r"\b(?:" + "|".join(re.escape(t) for t in AI_TERMS) + r")\b", re.IGNORECASE)

GREETING_KEYS = ["greeting", "greetingMessage", "welcomeMessage", "welcome_message", "welcomeText",
                 "introMessage", "initialMessage", "botName", "bot_name", "assistantName", "agentName"]
GREETING_CONFIG = re.compile(
    r"""["']?\b(?:""" + "|".join(GREETING_KEYS) + r""")\b["']?\s*[:=]\s*(["'`])((?:\\.|(?!\1).){1,300})\1""",
    re.IGNORECASE)
GREETING_LINE = re.compile(
    r"how can (?:i|we) help|ask me|chat with (?:us|me)|i'?m (?:a|an|your) [\w\s-]*(?:assistant|bot)",
    re.IGNORECASE)

# Providers behind browser AI API calls: chatbot meta.vendor -> provider.
PROVIDERS = {"OpenAI API": "OpenAI", "Anthropic API": "Anthropic", "Google Gemini API": "Google"}
# Google keys (AIza) are usually public Maps keys, so a key only implies OpenAI or Anthropic.
KEY_PROVIDERS = {"OpenAI": "OpenAI", "Anthropic": "Anthropic"}
ALIASES = {"OpenAI": ["OpenAI", "ChatGPT"], "Anthropic": ["Anthropic", "Claude"],
           "Google": ["Google", "Gemini"], "Tawk.to": ["Tawk.to", "Tawk"]}


# ---------- text helpers ----------

def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if s.strip()]


def sentence_with(text, pattern):
    """First sentence of text matching the compiled pattern, else None."""
    for s in sentences(text):
        if pattern.search(s):
            return s
    return None


def name_pattern(names):
    return re.compile(r"(?<![\w])(?:" + "|".join(re.escape(n) for n in names) + r")(?![\w])", re.IGNORECASE)


def _norm(text):
    return re.sub(r"\s+", " ", text or "").strip()


def quote_in(quote, source):
    return bool(quote) and _norm(quote) in _norm(source)


def snippet(text):
    return clip(mask_all_keys(text or ""), SNIPPET_MAX)


# ---------- model engine ----------

def _ask_anthropic(prompt):
    import anthropic
    client = anthropic.Anthropic()
    msg = client.messages.create(model=ANTHROPIC_MODEL, max_tokens=400, temperature=0,
                                 messages=[{"role": "user", "content": prompt}])
    return "".join(getattr(b, "text", "") for b in msg.content)


def _ask_openai(prompt):
    import openai
    client = openai.OpenAI()
    resp = client.chat.completions.create(model=OPENAI_MODEL, temperature=0, max_tokens=400,
                                          response_format={"type": "json_object"},
                                          messages=[{"role": "user", "content": prompt}])
    return resp.choices[0].message.content or ""


def model_backend():
    """The model call function to use, or None for the keyword path."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return _ask_anthropic
    if os.environ.get("OPENAI_API_KEY"):
        return _ask_openai
    return None


def ask_model(ask, question, source, answers):
    """{answer, quote} from the model, or None on any error or invalid reply."""
    if ask is None or not source:
        return None
    prompt = (
        f"{question}\n\nAnswer only with strict JSON: "
        f'{{"answer": one of {json.dumps(answers)}, "quote": "the exact sentence from the text that '
        f'supports the answer, copied character for character, or an empty string"}}.\n\n'
        f"TEXT:\n<<<\n{source}\n>>>"
    )
    try:
        reply = ask(prompt)
        m = re.search(r"\{.*\}", reply, re.DOTALL)
        data = json.loads(m.group(0) if m else reply)
        answer = str(data.get("answer", "")).strip().lower()
        quote = str(data.get("quote") or "").strip()
    except Exception as e:  # network, SDK missing, bad JSON: fall back to keywords
        print(f"policy: model unavailable ({type(e).__name__}), using keywords", flush=True)
        return None
    if answer not in answers:
        return None
    return {"answer": answer, "quote": quote}


def judged(model_reply, source, positive):
    """Accept a model reply only if its quote really is in the source text. A positive answer
    needs a quote; a negative one may come without. Returns (answer, quote) or None."""
    if not model_reply:
        return None
    answer, quote = model_reply["answer"], model_reply["quote"]
    if quote:
        return (answer, quote) if quote_in(quote, source) else None
    return None if answer == positive else (answer, "")


# ---------- findings ----------

def finding(raw, slug, title, severity, where, snip, fix, engine, meta=None):
    return {
        "id": f"{raw['site']}:disclosure:{slug}",
        "type": "disclosure",
        "title": title,
        "severity": severity,
        "method": "judged",
        "evidence": {"where": mask_all_keys(where), "snippet": snippet(snip)},
        "fix": fix,
        "meta": {"engine": engine, **(meta or {})},
    }


def greeting_snippets(raw):
    """Greeting / bot config text from inline scripts and page text. Keys masked."""
    found = []
    for s in raw.get("scripts") or []:
        if s.get("inline") and s.get("content"):
            found += [m.group(2) for m in GREETING_CONFIG.finditer(s["content"])]
    for line in (raw.get("page_text") or "").splitlines():
        if GREETING_LINE.search(line):
            found.append(line.strip())
    out = []
    for g in found:
        g = mask_all_keys(g.strip())
        if g and g not in out:
            out.append(g)
    return out


def bot_disclosure(raw, ask):
    """Question 1: does the chat say it's AI?"""
    where = page_url(raw)
    greetings = greeting_snippets(raw)
    if not greetings:
        return finding(raw, "bot-unknown", "Couldn't tell if the chat says it's AI", "low", where,
                       "No chat greeting text visible on the homepage",
                       "We couldn't see the chat greeting without opening it. "
                       "Check it tells visitors they're talking to an AI assistant, if it is one.", "keywords")
    source = "\n".join(greetings)
    reply = judged(ask_model(ask, "These are greeting and configuration texts of a website chat widget. "
                                  "Does the widget tell visitors that it is an AI / automated assistant? "
                                  "Answer \"unknown\" if the text isn't enough to tell.",
                             source, ["yes", "no", "unknown"]), source, "yes")
    if reply:
        engine, (answer, quote) = "model", reply
    else:
        engine = "keywords"
        hit = next((g for g in greetings if AI_RE.search(g)), None)
        answer, quote = ("yes", hit) if hit else ("no", "")
    quote = quote or max(greetings, key=len)
    if answer == "yes":
        return finding(raw, "bot-ai", "Chat says it's an AI assistant", "info", where, quote,
                       "Good: visitors know they're talking to AI.", engine)
    if answer == "no":
        return finding(raw, "bot-not-ai", "The chat assistant doesn't say it's AI", "medium", where, quote,
                       "If this chat is run by AI, EU rules (the AI Act) say visitors should be told they're "
                       "talking to AI. Ask your web person to add a line like 'I'm an AI assistant' to the greeting.",
                       engine)
    return finding(raw, "bot-unknown", "Couldn't tell if the chat says it's AI", "low", where, quote,
                   "We couldn't tell from the greeting whether the chat says it's AI. "
                   "Check it tells visitors they're talking to an AI assistant, if it is one.", engine)


def ai_vendors(findings):
    """Vendor names the policy should mention, in order, deduped."""
    names = []
    for f in findings:
        meta = f.get("meta") or {}
        name = None
        if f.get("type") == "chatbot" and meta.get("vendor"):
            name = PROVIDERS.get(meta["vendor"], meta["vendor"])
        elif f.get("type") == "key_leak" and meta.get("key_type"):
            name = KEY_PROVIDERS.get(short_name(meta["key_type"]))
        if name and name not in names:
            names.append(name)
    return names


def vendor_named(raw, vendor, policy_text, ask):
    """Is the vendor named in the policy? Returns (named, quote, engine)."""
    capped = policy_text[:POLICY_MAX]
    reply = judged(ask_model(ask, f"This is a website's privacy policy. Does it name {vendor} "
                                  f"as a service provider or data processor?",
                             capped, ["yes", "no"]), capped, "yes")
    return _pick(reply, policy_text, name_pattern(ALIASES.get(vendor, [vendor])))


def policy_mentions_ai(policy_text, ask):
    """Does the policy mention AI / chatbots / automated processing? Returns (yes, quote, engine)."""
    capped = policy_text[:POLICY_MAX]
    reply = judged(ask_model(ask, "This is a website's privacy policy. Does it mention artificial "
                                  "intelligence, chatbots, virtual assistants or automated processing?",
                             capped, ["yes", "no"]), capped, "yes")
    return _pick(reply, policy_text, AI_RE)


def _pick(reply, policy_text, pattern):
    """Model answer, unless it says "no" while the keyword pattern matches past the first
    POLICY_MAX chars, which the model never saw. Returns (yes, quote, engine)."""
    unseen = sentence_with(policy_text[POLICY_MAX:], pattern)
    if reply and (reply[0] == "yes" or unseen is None):
        return reply[0] == "yes", reply[1], "model"
    quote = unseen if reply else sentence_with(policy_text, pattern)
    return quote is not None, quote or "", "keywords"


def policy_findings(raw, vendors, ask):
    """Question 2: does the privacy policy name the AI providers on the page?"""
    policy = raw.get("privacy_policy")
    if not policy or not (policy.get("text") or "").strip():
        where = (policy or {}).get("url") or page_url(raw)
        return [finding(raw, "no-policy", "No privacy policy found on the homepage", "medium", where,
                        "No link to a privacy policy found on the homepage",
                        "Visitors can't find out what happens to their data. "
                        "Ask your web person to add a privacy policy and link it from every page.", "keywords")]
    where = policy.get("url") or page_url(raw)
    text = mask_all_keys(policy["text"])
    findings = []
    for vendor in vendors:
        named, quote, engine = vendor_named(raw, vendor, text, ask)
        if named:
            continue
        fallback = (sentence_with(text, AI_RE)
                    or sentence_with(text, name_pattern([short_name(v["name"]) for v in VENDORS]))
                    or f"{vendor} not named in the privacy policy")
        findings.append(finding(raw, f"policy-{slugify(vendor)}", f"Privacy policy doesn't mention {vendor}",
                                "medium", where, quote or fallback,
                                f"Your site uses {vendor} but your privacy policy doesn't say so. "
                                f"Ask your web person to add a line naming {vendor} and what it's used for.",
                                engine, {"vendor": vendor}))
    if vendors:
        mentions, quote, engine = policy_mentions_ai(text, ask)
        if mentions:
            findings.append(finding(raw, "policy-ai", "Privacy policy mentions AI or automated processing",
                                    "info", where, quote,
                                    "Good: your privacy policy tells visitors about AI. Keep it up to date.", engine))
        else:
            findings.append(finding(raw, "policy-ai", "Privacy policy doesn't mention AI or chatbots", "info",
                                    where, "No mention of AI, chatbots or automated processing",
                                    "Your site uses AI tools. Ask your web person to add a short line to your "
                                    "privacy policy saying what they are used for.", engine))
    return findings


def judge(raw, findings, ask=None):
    """All policy reader findings for one raw site dict, given that site's existing findings."""
    if raw.get("error"):
        return []
    out = []
    if any(f.get("type") == "chatbot" for f in findings):
        out.append(bot_disclosure(raw, ask))
    out += policy_findings(raw, ai_vendors(findings), ask)
    return out


# ---------- pipeline ----------

def _is_ours(f):
    return f.get("type") == "disclosure" and f.get("method") == "judged"


def run(raw_dir, findings_path):
    """Read raw files and findings.json, add disclosure findings, rescore, write findings.json back."""
    raw_dir, findings_path = Path(raw_dir), Path(findings_path)
    data = {"sites": []}
    if findings_path.exists():
        data = json.loads(findings_path.read_text(encoding="utf-8"))
    by_site = {s["site"]: s for s in data.setdefault("sites", [])}
    ask = model_backend()
    print(f"policy: engine {'model' if ask else 'keywords'}", flush=True)

    for path in sorted(raw_dir.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("error"):
            continue
        entry = by_site.get(raw["site"])
        if entry is None:
            entry = {"site": raw["site"], "final_url": raw.get("final_url"), "status": raw.get("status"),
                     "error": raw.get("error"), "score": None, "findings": []}
            data["sites"].append(entry)
            by_site[raw["site"]] = entry
        if raw.get("label"):
            entry["label"] = mask_all_keys(raw["label"])
        else:
            entry.pop("label", None)
        kept = [f for f in entry.get("findings", []) if not _is_ours(f)]
        new = judge(raw, kept, ask)
        entry["findings"] = merge_findings(kept, new)
        print(f"{raw['site']}  disclosure: {len(new)}", flush=True)

    for entry in data["sites"]:
        entry["score"] = compute_score(entry.get("findings", []), entry.get("error"))
    data["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = {"generated_at": data.pop("generated_at"), **data}
    findings_path.parent.mkdir(parents=True, exist_ok=True)
    findings_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data
