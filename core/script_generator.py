"""
Script Generator — uses Groq API (100% FREE).
Produces 25-30 second scripts (65-75 words).

VIRAL UPGRADES (based on 2025/26 YouTube Shorts algorithm research):
- Shorter = higher completion rate. 25-30s > 32s every time.
- Loop-bait ending that makes the video feel seamless to replay
- Share-bait CTA: "send this to someone who needs to see it" drives shares
  (shares are the strongest viral signal per YouTube's own data)
- Engaged Views are what matter now (not raw views) — so hook must stop the swipe
- Punctuation cues added to script output so TTS sounds more human
"""

import os, json, asyncio, httpx, logging
from datetime import datetime
from core.animal_tracker import get_used_animals, mark_animals_used, build_exclusion_prompt

log = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

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

def get_todays_subniche() -> str:
    now = datetime.now()
    hour_slot = now.hour // 6
    index = (now.timetuple().tm_yday * 4 + hour_slot) % len(SUBNICHES)
    return SUBNICHES[index]

def build_prompt(count: int, subniche: str, used_animals: list[str]) -> str:
    exclusion = build_exclusion_prompt(used_animals)
    return f"""You are a viral YouTube Shorts writer. You write like a hyped-up friend texting wild animal facts — casual, punchy, zero fluff. Generate {count} scripts about: "{subniche}"
{exclusion}

═══════════════════════════════════════
TARGET: 65-75 words TOTAL per script. 25-30 seconds spoken aloud.
SHORTER = BETTER. Every extra word is a viewer lost.
═══════════════════════════════════════

CRITICAL 2025 ALGORITHM FACTS (write around these):
1. COMPLETION RATE is king — if they watch to the end, you win. Keep it SHORT.
2. SHARES are the #1 viral signal — write something people HAVE to send to a friend
3. REPLAYS boost rank dramatically — make the ending loop back to the hook naturally
4. ENGAGED VIEWS > raw views — the hook must physically stop someone from swiping

PUNCTUATION RULES (non-negotiable — TTS voice uses these for natural pauses):
- Use "..." before the craziest reveal — forces a dramatic pause
- Use "—" for mid-sentence pivots and emphasis
- Use "!" for energy peaks — but max 2 per script
- Never end a sentence flatly if it can end with a punch

HOOK FORMULA (first 2 seconds decides everything):
Pick ONE of these proven formats:
1. WRONG FACT OPENER: Start with something that sounds impossible, then confirm it's real
2. SCALE SHOCK: "This [animal] can [action] — that's like a human [relatable comparison]"
3. VS BATTLE: "[Animal] vs [thing 10x bigger]. It wins. Every. Single. Time."
4. CHAOS NORMAL: State the most insane fact as if it's totally boring news

BODY RULES:
- ONE punchy comparison (make it relatable to everyday life)
- ONE "... wait for it ..." beat before the hardest-hitting fact
- Casual vocab: "this thing", "absolutely unhinged", "for no reason", "built different", "no, seriously"
- Real numbers only — made-up stats kill trust and shares

CTA STRATEGY (pick one per script, rotate):
TYPE A — DEBATE BAIT (forces comments): "Comment [X] or [Y]. No in between."
TYPE B — SHARE BAIT (forces shares — strongest viral signal): "Send this to someone who'd never believe it."
TYPE C — CHALLENGE (forces comments + shares): "Name ONE animal tougher than this. I'll wait."
TYPE D — WRONG ANSWERS (high comment volume): "Wrong answers only — what would you do against this thing?"

LOOP HOOK STRATEGY:
The loop_hook shows in the LAST 3 SECONDS. It must:
- Reference something specific from the video (not generic)
- Make viewer feel they "missed something" → triggers replay
- Examples: "Wait... did you catch HOW FAST it actually is?"
            "Rewatch the part about the punch. It doesn't make sense."
            "The comparison at the start is even crazier now, right?"

Respond ONLY with valid JSON array. No markdown. Start with [

[
  {{
    "title": "Unhinged title under 55 chars — sounds impossible but true #Shorts",
    "animal_keyword": "single animal name for Pexels video search",
    "hook": "1-2 sentences. STOPS the swipe. 12-18 words. Uses punctuation for drama.",
    "body": "2-3 sentences. ONE comparison. ONE '... wait for it ...' beat. 42-48 words. Conversational.",
    "cta": "One of TYPE A/B/C/D above. 8-12 words MAX. No generic 'follow for more'.",
    "tags": ["#Shorts", "#AnimalFacts", "#Wildlife", "#Animals", "#Facts"],
    "emoji": "most chaotic relevant emoji",
    "shock_word": "ONE all-caps word for giant overlay e.g. IMPOSSIBLE / INSANE / WAIT / NOPE / WILD",
    "loop_hook": "6-9 words referencing a SPECIFIC moment in THIS video to bait replay"
  }}
]

TONE CALIBRATION — copy this energy exactly:

BAD hook: "The mantis shrimp has a very powerful punch that scientists have studied."
GOOD hook: "This shrimp punches so fast... it literally boils the water. Yes. Really."

BAD body: "The pistol shrimp creates a cavitation bubble when it snaps its claw."
GOOD body: "It snaps its claw and the shockwave hits 218 decibels — that's louder than a gunshot. A shrimp. Louder than a gun."

BAD CTA: "Follow for more amazing animal facts every day!"
GOOD CTA: "Send this to someone who needs to know shrimp are terrifying."

BAD loop_hook: "Watch this video again for more facts."
GOOD loop_hook: "Rewatch the decibel number. It still doesn't make sense."

FINAL RULES:
- hook + body + cta = 65-75 words STRICTLY
- Every animal must be different from others in this batch
- ALL facts must be 100% accurate with real numbers — fact errors destroy share rate
- Reads naturally when spoken fast — no tongue-twisters, no awkward phrasing
- No visual references ("as you can see") — audio only"""

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

def validate_scripts(scripts: list) -> list:
    fixed = []
    for s in scripts:
        full_text = f"{s.get('hook','')} {s.get('body','')} {s.get('cta','')}"
        word_count = len(full_text.split())
        log.info(f"Script '{s.get('title','?')}' — {word_count} words — animal: {s.get('animal_keyword','?')}")

        if word_count < 55:
            log.warning(f"Too short ({word_count} words) — padding")
            s['body'] = s.get('body', '') + " Scientists are still figuring out how this is even possible."
        elif word_count > 80:
            log.warning(f"Too long ({word_count} words) — trimming")
            body_words = s.get('body', '').split()
            s['body'] = " ".join(body_words[:45])

        if not s.get('shock_word'):
            s['shock_word'] = 'WAIT'

        if not s.get('loop_hook'):
            s['loop_hook'] = "Wait... did you catch that detail?"

        # Ensure loop_hook is specific, not generic
        generic_hooks = ["watch again", "watch this again", "watch more", "see more"]
        if any(g in s.get('loop_hook', '').lower() for g in generic_hooks):
            animal = s.get('animal_keyword', 'this animal')
            s['loop_hook'] = f"Rewatch the part about the {animal}. Still insane."

        fixed.append(s)
    return fixed

async def _try_groq(prompt: str) -> list:
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    body = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.88,   # Slightly higher = more creative hooks
        "max_tokens": 3000,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(GROQ_URL, headers=headers, json=body)
    if resp.status_code == 429:
        raise RuntimeError("Groq rate limit")
    resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"]
    return parse_json(raw)

async def _try_gemini(prompt: str) -> list:
    url = f"{GEMINI_URL}?key={GEMINI_API_KEY}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.88, "maxOutputTokens": 3000}
    }
    for attempt in range(3):
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=body)
        if resp.status_code == 429:
            wait = 60 * (attempt + 1)
            log.warning(f"Gemini rate limit — waiting {wait}s")
            await asyncio.sleep(wait)
            continue
        resp.raise_for_status()
        raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        return parse_json(raw)
    raise RuntimeError("Gemini quota exhausted")

async def generate_scripts(count: int = 1) -> list[dict]:
    if not GROQ_API_KEY and not GEMINI_API_KEY:
        raise ValueError(
            "No API key found!\n"
            "Add GROQ_API_KEY=gsk_xxx (free at console.groq.com)"
        )

    subniche = get_todays_subniche()
    log.info(f"Sub-niche this slot: {subniche}")

    used_animals = get_used_animals()
    log.info(f"Animals used so far: {len(used_animals)} — {used_animals[-5:] if used_animals else 'none yet'}")

    prompt = build_prompt(count, subniche, used_animals)

    scripts = None

    if GROQ_API_KEY:
        try:
            scripts = await _try_groq(prompt)
        except Exception as e:
            log.warning(f"Groq failed: {e} — trying Gemini...")

    if scripts is None and GEMINI_API_KEY:
        try:
            scripts = await _try_gemini(prompt)
        except Exception as e:
            log.error(f"Gemini failed: {e}")
            raise RuntimeError("All AI providers failed.")

    if scripts is None:
        raise RuntimeError("All AI providers failed. Check your API keys.")

    scripts = validate_scripts(scripts)

    new_animals = [s.get("animal_keyword", "").lower().strip() for s in scripts if s.get("animal_keyword")]
    mark_animals_used(new_animals)
    log.info(f"Marked {len(new_animals)} new animals as used: {new_animals}")

    log.info(f"Generated {len(scripts)} scripts via AI (free)")
    return scripts
