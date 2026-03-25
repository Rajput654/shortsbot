"""
Script Generator v4.0 — Viral Scenario/POV Format

COMPLETE OVERHAUL v4.0:
- FORMAT CHANGE: From "AI narrator voiceover facts" to "scenario-driven story
  with text overlays + minimal reaction voice." This matches what actually goes
  viral: meme-style storytelling where the VISUAL TEXT tells the story.
- SCENARIO STRUCTURE: Each video is a mini-story with setup → escalation →
  punchline → loop, told through on-screen text beats + animal footage.
- VOICE ROLE CHANGED: Voice is now the animal's internal monologue (funny,
  personality-driven) OR a short observer comment — NOT a documentary narrator.
- TEXT OVERLAY BEATS: Script now generates timed "scene_beats" — big bold
  text moments that appear on screen like meme captions driving the joke.
- POV FORMATS: "POV: you're the dog when...", "When your cat does X", "Me
  trying to Y" — formats proven to get 10M+ views on animal shorts.
- 55-SECOND TARGET: Data shows 50-60s Shorts get 1.7M avg views vs 15s.
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

# Viral scenario formats proven to work for animal shorts
VIRAL_SCENARIO_FORMATS = [
    "POV: you are the [animal] when [relatable situation]",
    "When your [animal] [does something funny/relatable]",
    "The [animal] when [unexpected situation] hits different",
    "Me as a [animal] discovering [thing] for the first time",
    "That moment when your [animal] realizes [funny truth]",
    "[Animal] trying to [fail at human thing] is sending me 💀",
    "Nobody: ... [Animal]: [absurd reaction to normal thing]",
    "The [animal] understood the assignment 🎯",
    "My [animal] said 'not today' and proceeded to [chaos]",
    "Things my [animal] does that I can't explain but fully respect",
]

# Subniches that consistently get shares
SUBNICHES = [
    "pets acting like dramatic humans",
    "animals with zero survival instincts",
    "animals that fully understood the assignment",
    "pets catching their owners in 4K",
    "animals having an existential crisis over nothing",
    "pets that run the household and everyone knows it",
    "wild animals behaving like suburban dads",
    "baby animals discovering the world for the first time",
    "animals that chose chaos and we respect it",
    "pets absolutely roasting their owners without saying a word",
]

LENGTH_MODES = ["short", "long", "long", "long"]

# What ACTUALLY viral animal shorts look like — scenario text overlay format
FEW_SHOT_VIRAL = """
═══════════════════════════════════════════════
VIRAL FORMAT EXAMPLES (10M+ views each)
These use TEXT OVERLAYS as the main storytelling device, not just narration.
The voice is OPTIONAL or plays the animal's inner monologue.
═══════════════════════════════════════════════

VIRAL EXAMPLE 1 — POV Format (hook: "POV you're the dog"):
{
  "title": "The dog understood the assignment 😭 #Shorts",
  "animal_keyword": "golden retriever",
  "format_type": "pov",
  "scene_beats": [
    {"timestamp": 0.0,  "overlay_text": "POV: You're the dog", "style": "pov_header", "voice_line": ""},
    {"timestamp": 1.5,  "overlay_text": "Owner says 'we're not going to the vet'", "style": "setup", "voice_line": "okay cool cool"},
    {"timestamp": 4.0,  "overlay_text": "Owner grabs the keys", "style": "escalate", "voice_line": "..."},
    {"timestamp": 6.0,  "overlay_text": "Owner says 'just a quick errand'", "style": "escalate", "voice_line": "I was BORN at night"},
    {"timestamp": 9.5,  "overlay_text": "The dog:", "style": "reaction_setup", "voice_line": ""},
    {"timestamp": 11.0, "overlay_text": "SIT DOWN PROTEST ACTIVATED 🪑", "style": "punchline", "voice_line": "not today chief"},
    {"timestamp": 14.0, "overlay_text": "45 minutes later...", "style": "escalate", "voice_line": "I will die on this floor"},
    {"timestamp": 17.0, "overlay_text": "Still going 💪", "style": "loop_close", "voice_line": "see you never, vet"},
    {"timestamp": 19.5, "overlay_text": "Send this to someone whose dog does this 👇", "style": "cta", "voice_line": ""}
  ],
  "voice_style": "animal_internal_monologue",
  "voice_tone": "deadpan comedic",
  "loop_hook": "The dog understood something we didn't 👀",
  "pinned_comment": "Does your dog do the sit-down protest too? 🐾",
  "seo_tags": ["#dogsoftiktok", "#funnydog", "#pets", "#pov", "#shorts", "#animals"]
}

VIRAL EXAMPLE 2 — "When your X" Format:
{
  "title": "When your cat catches you lying 😭 #Shorts",
  "animal_keyword": "cat",
  "format_type": "when_your",
  "scene_beats": [
    {"timestamp": 0.0,  "overlay_text": "When your cat hears you say", "style": "setup", "voice_line": ""},
    {"timestamp": 1.5,  "overlay_text": "'I don't feed the cat'", "style": "setup", "voice_line": ""},
    {"timestamp": 3.5,  "overlay_text": "To the vet.", "style": "escalate", "voice_line": ""},
    {"timestamp": 5.0,  "overlay_text": "The cat:", "style": "reaction_setup", "voice_line": ""},
    {"timestamp": 6.5,  "overlay_text": "👁️👁️", "style": "punchline", "voice_line": "I remember everything"},
    {"timestamp": 9.0,  "overlay_text": "Scientists: cats don't hold grudges", "style": "escalate", "voice_line": ""},
    {"timestamp": 11.5, "overlay_text": "The cat at 3AM:", "style": "escalate", "voice_line": ""},
    {"timestamp": 13.0, "overlay_text": "*knocks everything off the counter*", "style": "punchline", "voice_line": "this is for the vet"},
    {"timestamp": 17.0, "overlay_text": "Tag someone with a cat like this 😭", "style": "cta", "voice_line": ""}
  ],
  "voice_style": "animal_internal_monologue",
  "voice_tone": "cold and calculating",
  "loop_hook": "The cat was always watching. Always.",
  "pinned_comment": "What has your cat done for revenge? 💀",
  "seo_tags": ["#catsoftiktok", "#funnycat", "#catbehavior", "#pov", "#shorts", "#relatable"]
}

═══════════════════════════════════════════════
KEY RULES:
- scene_beats drive the story — each one is a BIG TEXT MOMENT on screen
- voice_line is SHORT (3-6 words max) or empty — it's the animal's inner voice
- The joke/story is told by TEXT + TIMING, not explained by narration
- Total beats should cover 18-55 seconds depending on length_mode
- punchline beats use ALL CAPS or emoji for emphasis
- CTA always last beat, always share-bait
═══════════════════════════════════════════════
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
        return winner
    now = datetime.now()
    hour_slot = now.hour // 6
    return LENGTH_MODES[hour_slot % len(LENGTH_MODES)]


def build_prompt(count: int, subniche: str, used_animals: list[str], length_mode: str) -> str:
    exclusion = build_exclusion_prompt(used_animals)

    if length_mode == "short":
        beat_instructions = """
LENGTH: SHORT (15-20 seconds)
- 6-8 scene_beats total
- Timestamps from 0.0 to ~19.0
- Ultra-tight punchline — setup → punchline → CTA only
- Best for: single reaction moments, one joke, one twist"""
    else:
        beat_instructions = """
LENGTH: LONG (45-55 seconds)
- 10-14 scene_beats total
- Timestamps from 0.0 to ~53.0
- Full escalating story arc: Setup → 2-3 escalations → punchline → aftermath → CTA
- Pattern interrupts between beats (unexpected turns that make viewer stay)
- The punchline should feel EARNED by the build-up"""

    format_choice = "pov OR when_your OR nobody_animal OR understood_assignment"

    return f"""You are a viral YouTube Shorts creator specializing in funny animal content.
The best animal shorts are NOT documentary-style narration videos.
They are SCENARIO-DRIVEN stories told through big text overlays on screen.
The voice (if any) is SHORT inner monologue — 3-6 words max per beat.

Write {count} viral animal short script(s) about the theme: "{subniche}"
{exclusion}

{FEW_SHOT_VIRAL}

{beat_instructions}

FORMAT REQUIREMENTS:
- format_type: {format_choice}
- Each scene_beat MUST have: timestamp (float), overlay_text (string), style (string), voice_line (string — can be empty "")
- overlay_text styles: "pov_header", "setup", "escalate", "reaction_setup", "punchline", "aftermath", "loop_close", "cta"
- voice_style: "animal_internal_monologue" or "deadpan_observer" or "none"
- voice_tone: short description of delivery vibe (e.g. "dramatic and betrayed", "smug", "dead inside")
- Punchline beats: use CAPS, emoji, *action text* for maximum visual impact
- CTA beat: always share-bait ("Tag someone...", "Send this to...", "If your pet does this...")
- animal_keyword: the specific animal (will be used to fetch footage from Pexels)
- loop_hook: 1 sentence shown as final text that feeds curiosity back to start

CRITICAL: The story must work WITHOUT audio — text overlays carry the joke.
The voice_lines are just flavor/inner monologue, not the main storytelling.

Respond ONLY with a raw JSON array. No markdown, no backticks, no explanation.

[
  {{
    "title": "MAX 48 chars with curiosity gap #Shorts",
    "animal_keyword": "specific animal name for Pexels search",
    "format_type": "pov | when_your | nobody_animal | understood_assignment",
    "length_mode": "{length_mode}",
    "scene_beats": [
      {{"timestamp": 0.0, "overlay_text": "Opening text hook", "style": "pov_header", "voice_line": ""}},
      {{"timestamp": 2.5, "overlay_text": "Next beat", "style": "setup", "voice_line": "optional 3-6 word animal voice"}},
      "...more beats...",
      {{"timestamp": 19.0, "overlay_text": "Tag someone who needs to see this 👇", "style": "cta", "voice_line": ""}}
    ],
    "voice_style": "animal_internal_monologue",
    "voice_tone": "dramatic and betrayed",
    "loop_hook": "One sentence to loop viewers back to start",
    "pinned_comment": "Engaging debate-bait question",
    "seo_tags": ["#tag1", "#tag2", "#tag3", "#tag4", "#tag5", "#shorts"]
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
    """Validate and repair generated scripts."""
    fixed = []
    for s in scripts:
        # Title
        if s.get("title"):
            s["title"] = _enforce_title_length(s["title"], max_chars=48)
        else:
            animal = s.get("animal_keyword", "animal")
            s["title"] = f"This {animal} understood the assignment #Shorts"

        # Ensure scene_beats exist and are well-formed
        beats = s.get("scene_beats", [])
        if not beats:
            # Build fallback beats from any available fields
            animal = s.get("animal_keyword", "animal")
            beats = [
                {"timestamp": 0.0,  "overlay_text": f"POV: you're the {animal}", "style": "pov_header", "voice_line": ""},
                {"timestamp": 2.0,  "overlay_text": "When everything is fine", "style": "setup", "voice_line": "vibing"},
                {"timestamp": 5.0,  "overlay_text": "Until it's not.", "style": "escalate", "voice_line": "..."},
                {"timestamp": 8.0,  "overlay_text": f"THE {animal.upper()}:", "style": "reaction_setup", "voice_line": ""},
                {"timestamp": 10.0, "overlay_text": "CHAOS ACTIVATED 💀", "style": "punchline", "voice_line": "not my problem"},
                {"timestamp": 14.0, "overlay_text": "Tag someone who gets it 👇", "style": "cta", "voice_line": ""},
            ]
        # Ensure each beat has required fields
        for beat in beats:
            beat.setdefault("timestamp", 0.0)
            beat.setdefault("overlay_text", "")
            beat.setdefault("style", "setup")
            beat.setdefault("voice_line", "")

        # Sort by timestamp
        beats.sort(key=lambda b: b["timestamp"])
        s["scene_beats"] = beats

        # Other defaults
        if not s.get("voice_style"):
            s["voice_style"] = "animal_internal_monologue"
        if not s.get("voice_tone"):
            s["voice_tone"] = "deadpan comedic"
        if not s.get("loop_hook"):
            animal = s.get("animal_keyword", "animal")
            s["loop_hook"] = f"The {animal} was always built different 👀"
        if not s.get("seo_tags") or len(s.get("seo_tags", [])) < 3:
            animal_tag = s.get("animal_keyword", "animal").replace(" ", "").lower()
            s["seo_tags"] = [f"#{animal_tag}", "#funnyanimals", "#pets", "#pov", "#shorts", "#relatable"]
        if not s.get("pinned_comment"):
            animal = s.get("animal_keyword", "this animal")
            s["pinned_comment"] = f"Does your {animal} do this? Drop a 🐾"
        s["length_mode"] = length_mode

        # Build a minimal voice narration from voice_lines for TTS
        # (only the non-empty voice_line beats get spoken)
        voice_lines = [b["voice_line"] for b in beats if b.get("voice_line", "").strip()]
        s["voice_narration"] = "  ".join(voice_lines) if voice_lines else ""

        fixed.append(s)
    return fixed


async def _try_groq(prompt: str) -> list:
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY not set")
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    body = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.92,
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
        "generationConfig": {"temperature": 0.92, "maxOutputTokens": 4000}
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
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set")
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    body = {
        "model": "claude-haiku-4-5-20251001",
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

    subniche    = get_todays_subniche()
    length_mode = get_optimised_length_mode()

    log.info(f"Sub-niche: {subniche}")
    log.info(f"Length mode: {length_mode}")

    used_animals = get_used_animals()
    log.info(f"Animals used so far: {len(used_animals)}")

    prompt = build_prompt(count, subniche, used_animals, length_mode)
    scripts = None

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
        raise RuntimeError("All AI providers failed. Check your API keys.")

    scripts = validate_scripts(scripts, length_mode)

    new_animals = [s.get("animal_keyword", "").lower().strip() for s in scripts if s.get("animal_keyword")]
    mark_animals_used(new_animals)
    log.info(f"Generated {len(scripts)} scripts | animals: {new_animals}")
    return scripts
