"""
Script Generator v3.1 — Groq (primary) → Gemini → Claude (fallbacks).

CHANGES v3.1:
- Added Anthropic Claude as third fallback provider.
- Improved 400 error logging: now prints the actual response body so you
  can see exactly why Groq/Gemini rejected the request.
- Reduced prompt token count slightly to avoid edge-case 400s on Groq.
"""

import os, json, asyncio, httpx, logging
from datetime import datetime
from core.animal_tracker import get_used_animals, mark_animals_used, build_exclusion_prompt

log = logging.getLogger(__name__)

GROQ_API_KEY      = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY    = os.getenv("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
CLAUDE_URL = "https://api.anthropic.com/v1/messages"

PERFORMANCE_LOG = os.path.join(os.path.dirname(__file__), "..", "performance_log.json")

SUBNICHES = [
    "Animals with abilities so ridiculous they sound made up",
    "Animals that would absolutely destroy humans in a fight",
    "Deep sea creatures that look like nightmares",
    "Animals with superpowers that make humans look pathetic",
    "Animal world records so extreme they break your brain",
    "Animals that cheat death in the most insane ways",
    "Baby animals that are secretly terrifying killers",
    "Animals that are way smarter than your average human",
    "Prehistoric monsters that make T-Rex look cute",
    "Animals that science still cannot explain",
]

LENGTH_MODES = ["short", "short", "long", "long"]

# ── Few-shot examples injected into every prompt ──────────────────────────────
FEW_SHOT_VIRAL = """
VIRAL EXAMPLE 1 (hook_type: wrong_fact, length: short, ~38 words):
{"title":"The mantis shrimp punches at bullet speed #Shorts","animal_keyword":"mantis shrimp","hook":"This tiny shrimp hits harder than a bullet.","body":"The mantis shrimp strikes at 50 mph... Wait. That's faster than a pro boxer. Nope — it actually breaks aquarium glass.","cta":"Send this to someone who thinks size matters.","shock_word":"IMPOSSIBLE","loop_hook":"So next time you see something tiny... remember the shrimp."}

VIRAL EXAMPLE 2 (hook_type: vs_battle, length: long, ~175 words):
{"title":"The wolverine vs a grizzly bear #Shorts","animal_keyword":"wolverine","hook":"A 30-pound animal just chased a grizzly bear off its kill.","body":"The wolverine. It doesn't have claws — it has hooks attached to rage. Scientists actually... watched wolverines steal food from wolves, black bears, and yes, grizzlies. Wait. How? Its skeleton is built to take hits. Its jaws can crush frozen bone. And it never — ever — backs down. Nope. Not from anything. One researcher watched a wolverine hold a carcass for six hours against three wolves. Six hours. That's not survival. That's dominance.","cta":"Tag someone with wolverine energy.","shock_word":"NEVER","loop_hook":"Still think bears are the scariest thing in the forest?"}

AVOID: Hooks starting with 'Did you know', passive body text, 'like and subscribe' CTAs, titles over 48 chars.
"""


def get_todays_subniche() -> str:
    now = datetime.now()
    hour_slot = now.hour // 6
    index = (now.timetuple().tm_yday * 4 + hour_slot) % len(SUBNICHES)
    return SUBNICHES[index]


def _load_performance_data() -> dict:
    if not os.path.exists(PERFORMANCE_LOG):
        return {"videos": []}
    try:
        with open(PERFORMANCE_LOG, "r") as f:
            return json.load(f)
    except Exception:
        return {"videos": []}


def get_optimised_length_mode() -> str:
    data = _load_performance_data()
    videos = data.get("videos", [])

    short_evrs = [v["engaged_view_rate"] for v in videos if v.get("length_mode") == "short" and v.get("engaged_view_rate", 0) > 0]
    long_evrs  = [v["engaged_view_rate"] for v in videos if v.get("length_mode") == "long"  and v.get("engaged_view_rate", 0) > 0]

    if len(short_evrs) >= 3 and len(long_evrs) >= 3:
        avg_short = sum(short_evrs) / len(short_evrs)
        avg_long  = sum(long_evrs)  / len(long_evrs)
        winner = "short" if avg_short > avg_long else "long"
        log.info(f"Length mode optimiser: short EVR={avg_short:.1%} long EVR={avg_long:.1%} → using '{winner}'")
        return winner

    now = datetime.now()
    hour_slot = now.hour // 6
    return LENGTH_MODES[hour_slot % len(LENGTH_MODES)]


def get_best_hook_types() -> list[str]:
    data = _load_performance_data()
    videos = data.get("videos", [])

    evr_by_type: dict[str, list[float]] = {}
    for v in videos:
        ht = v.get("hook_type", "unknown")
        evr = v.get("engaged_view_rate", 0)
        if ht and evr > 0:
            evr_by_type.setdefault(ht, []).append(evr)

    ranked = sorted(
        [(ht, sum(evrs)/len(evrs)) for ht, evrs in evr_by_type.items() if len(evrs) >= 2],
        key=lambda x: x[1], reverse=True
    )

    if ranked:
        top = [ht for ht, _ in ranked[:2]]
        log.info(f"Hook type A/B: top performers = {ranked[:3]}")
        return top

    return ["wrong_fact", "vs_battle", "scale_shock", "chaos_normal"]


def load_performance_feedback() -> str:
    data = _load_performance_data()
    videos = data.get("videos", [])
    if len(videos) < 5:
        return ""

    def get_evr(e):
        return e.get("engaged_view_rate", 0)

    scores = [get_evr(e) for e in videos if get_evr(e) > 0]
    if not scores:
        return ""

    avg = sum(scores) / len(scores)
    top = [v for v in videos if get_evr(v) > avg * 1.5]
    bad = [v for v in videos if 0 < get_evr(v) < avg * 0.5]

    lines = ["\n\nALGORITHM FEEDBACK LOOP:"]
    if top:
        lines.append("VIRAL PATTERNS (REPLICATE):")
        for v in top[-3:]:
            lines.append(f"  - [{v.get('hook_type','')}] {v.get('title','')} (EVR: {get_evr(v):.1%})")
    if bad:
        lines.append("SWIPE-AWAY PATTERNS (AVOID):")
        for v in bad[-3:]:
            lines.append(f"  - [{v.get('hook_type','')}] {v.get('title','')} (EVR: {get_evr(v):.1%})")
    return "\n".join(lines)


def build_prompt(count: int, subniche: str, used_animals: list[str],
                 length_mode: str, best_hook_types: list[str]) -> str:
    exclusion = build_exclusion_prompt(used_animals)
    performance_feedback = load_performance_feedback()
    hook_preference = f"PREFERRED hook_types for this run (highest EVR): {', '.join(best_hook_types)}"

    if length_mode == "short":
        length_instructions = """TARGET: 13-SECOND ULTRA-SHORT (38-42 words, title MAX 48 chars).
- Aim for 100% completion rate.
- Loop MUST be seamless: end of CTA leads back into hook."""
    else:
        length_instructions = """TARGET: 45-55 SECOND DEEP-DIVE (155-175 words, title MAX 48 chars).
- Escalating stakes: Fact 1 weird, Fact 2 scary, Fact 3 impossible.
- At least 3 pattern interrupts (Wait... / Nope. / Actually...)."""

    return f"""You are a master of YouTube Shorts virality. Write {count} scripts about "{subniche}".
{exclusion}
{performance_feedback}
{hook_preference}

{FEW_SHOT_VIRAL}
{length_instructions}

VIRAL RULES:
1. INVOLUNTARY REPLAY: Script end resolves the hook setup.
2. NO 'AS YOU CAN SEE': Audio-only engagement.
3. TYPE B CTA: Share-bait only. "Send this to someone who..."
4. PATTERN INTERRUPTS: Use 'Wait...', 'Nope.', or 'Actually...' in body.
5. TITLE: MAX 48 characters including spaces. Curiosity gap. No filler.

Respond ONLY with a raw JSON array. No markdown, no backticks, no preamble.

[
  {{
    "title": "Max 48 chars with curiosity gap #Shorts",
    "animal_keyword": "animal name",
    "length_mode": "{length_mode}",
    "hook": "Must stop the swipe in 1.5 seconds.",
    "body": "Fast paced. Use '...' for pauses. Min 3 pattern interrupts for long mode.",
    "cta": "TYPE B focus (Share Bait).",
    "shock_word": "ONE all-caps word e.g. IMPOSSIBLE / INSANE / WAIT",
    "loop_hook": "1-2 sentences bridging CTA back to hook.",
    "hook_type": "wrong_fact | scale_shock | vs_battle | chaos_normal",
    "cta_type": "B",
    "seo_tags": ["#tag1", "#tag2", "#tag3", "#tag4", "#tag5"],
    "pinned_comment": "Debate-bait question e.g. 'Would you survive this animal?'"
  }}
]"""


def parse_json(raw: str) -> list:
    raw = raw.strip()
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0].strip()
    start = raw.find("[")
    end = raw.rfind("]") + 1
    if start == -1 or end == 0:
        raise ValueError(f"No JSON array in response: {raw[:200]}")
    return json.loads(raw[start:end])


def _enforce_title_length(title: str, max_chars: int = 48) -> str:
    if len(title) <= max_chars:
        return title
    has_shorts = "#Shorts" in title or "#shorts" in title
    base = title.replace(" #Shorts", "").replace(" #shorts", "").strip()
    suffix = " #Shorts"
    available = max_chars - len(suffix)
    if len(base) > available:
        base = base[:available - 1].rstrip() + "…"
    return base + (suffix if has_shorts else "")


def validate_scripts(scripts: list, length_mode: str) -> list:
    fixed = []
    for s in scripts:
        if s.get("title"):
            s["title"] = _enforce_title_length(s["title"], max_chars=48)
        if not s.get("shock_word"):
            s["shock_word"] = "WAIT"
        if not s.get("loop_hook") or len(s.get("loop_hook", "").split()) < 3:
            s["loop_hook"] = f"Wait... did you catch that? Look at the {s.get('animal_keyword', 'animal')} again."
        if not s.get("seo_tags") or len(s.get("seo_tags", [])) < 3:
            animal_tag = s.get("animal_keyword", "animal").replace(" ", "").lower()
            s["seo_tags"] = [f"#{animal_tag}", "#wildlife", "#animalfacts", "#shorts", "#nature"]
        if not s.get("pinned_comment"):
            animal = s.get("animal_keyword", "this animal")
            s["pinned_comment"] = f"Could you survive an encounter with a {animal}? Drop your answer below 👇"
        s["length_mode"] = length_mode
        fixed.append(s)
    return fixed


async def _try_groq(prompt: str) -> list:
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY not set")
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    body = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.88,
        "max_tokens": 4000,
    }
    for attempt in range(3):
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(GROQ_URL, headers=headers, json=body)
        if resp.status_code == 429:
            wait_time = 60 * (attempt + 1)
            log.warning(f"Groq rate limit — waiting {wait_time}s...")
            await asyncio.sleep(wait_time)
            continue
        if resp.status_code == 400:
            # Log full response body so you can see exactly what went wrong
            log.error(f"Groq 400 Bad Request — response body: {resp.text}")
            resp.raise_for_status()
        resp.raise_for_status()
        return parse_json(resp.json()["choices"][0]["message"]["content"])
    raise RuntimeError("Groq rate limit exhausted after 3 attempts.")


async def _try_gemini(prompt: str) -> list:
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY not set")
    url = f"{GEMINI_URL}?key={GEMINI_API_KEY}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.88, "maxOutputTokens": 4000}
    }
    for attempt in range(3):
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=body)
        if resp.status_code == 429:
            wait = 60 * (attempt + 1)
            log.warning(f"Gemini rate limit — waiting {wait}s")
            await asyncio.sleep(wait)
            continue
        if resp.status_code == 400:
            log.error(f"Gemini 400 Bad Request — response body: {resp.text}")
            resp.raise_for_status()
        resp.raise_for_status()
        return parse_json(resp.json()["candidates"][0]["content"]["parts"][0]["text"])
    raise RuntimeError("Gemini quota exhausted")


async def _try_claude(prompt: str) -> list:
    """Anthropic Claude as third fallback provider."""
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set")
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    body = {
        "model": "claude-haiku-4-5-20251001",   # Fastest + cheapest Anthropic model
        "max_tokens": 4000,
        "messages": [{"role": "user", "content": prompt}],
    }
    for attempt in range(3):
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(CLAUDE_URL, headers=headers, json=body)
        if resp.status_code == 429:
            wait = 60 * (attempt + 1)
            log.warning(f"Claude rate limit — waiting {wait}s")
            await asyncio.sleep(wait)
            continue
        if resp.status_code == 400:
            log.error(f"Claude 400 Bad Request — response body: {resp.text}")
            resp.raise_for_status()
        resp.raise_for_status()
        return parse_json(resp.json()["content"][0]["text"])
    raise RuntimeError("Claude rate limit exhausted after 3 attempts.")


async def generate_scripts(count: int = 1) -> list[dict]:
    if not GROQ_API_KEY and not GEMINI_API_KEY and not ANTHROPIC_API_KEY:
        raise ValueError(
            "No API key found! Set at least one of:\n"
            "  GROQ_API_KEY      — free at console.groq.com\n"
            "  GEMINI_API_KEY    — free at aistudio.google.com\n"
            "  ANTHROPIC_API_KEY — paid, at console.anthropic.com"
        )

    subniche       = get_todays_subniche()
    length_mode    = get_optimised_length_mode()
    best_hook_types = get_best_hook_types()

    log.info(f"Sub-niche: {subniche}")
    log.info(f"Length mode: {length_mode} (data-driven)")
    log.info(f"Hook types (best EVR): {best_hook_types}")

    used_animals = get_used_animals()
    log.info(f"Animals used so far: {len(used_animals)}")

    prompt = build_prompt(count, subniche, used_animals, length_mode, best_hook_types)

    scripts = None

    # ── Provider waterfall: Groq → Gemini → Claude ────────────────────────────
    if GROQ_API_KEY:
        try:
            scripts = await _try_groq(prompt)
            log.info("Scripts generated via Groq.")
        except Exception as e:
            log.warning(f"Groq failed: {e} — trying Gemini...")

    if scripts is None and GEMINI_API_KEY:
        try:
            scripts = await _try_gemini(prompt)
            log.info("Scripts generated via Gemini.")
        except Exception as e:
            log.warning(f"Gemini failed: {e} — trying Claude...")

    if scripts is None and ANTHROPIC_API_KEY:
        try:
            scripts = await _try_claude(prompt)
            log.info("Scripts generated via Claude (Anthropic).")
        except Exception as e:
            log.error(f"Claude failed: {e}")

    if scripts is None:
        raise RuntimeError(
            "All AI providers failed. Check your API keys in GitHub Secrets:\n"
            "  GROQ_API_KEY / GEMINI_API_KEY / ANTHROPIC_API_KEY"
        )

    scripts = validate_scripts(scripts, length_mode)

    new_animals = [s.get("animal_keyword", "").lower().strip() for s in scripts if s.get("animal_keyword")]
    mark_animals_used(new_animals)
    log.info(f"Marked {len(new_animals)} new animals: {new_animals}")
    log.info(f"Generated {len(scripts)} scripts")
    return scripts
