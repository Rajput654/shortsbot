"""
Script Generator — uses Groq API (100% FREE).

UPDATES:
- Scripts now output niche-specific SEO tags per animal (not just generic #Animals)
- Scripts now output a "pinned_comment" debate question field
- Performance feedback loop: reads performance_log.json and avoids
  hook styles / animals that underperformed (< avg views)
- Two length modes: "short" (~13s / 38–42 words) and "long" (~55–60s / 170–180 words)
"""

import os, json, asyncio, httpx, logging
from datetime import datetime
from core.animal_tracker import get_used_animals, mark_animals_used, build_exclusion_prompt

log = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

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

# Length modes: alternate to hit both viral sweet spots (13s and 60s)
LENGTH_MODES = ["short", "long"]


def get_todays_subniche() -> str:
    now = datetime.now()
    hour_slot = now.hour // 6
    index = (now.timetuple().tm_yday * 4 + hour_slot) % len(SUBNICHES)
    return SUBNICHES[index]


def get_length_mode() -> str:
    """Alternate between short (13s) and long (60s) based on upload slot."""
    now = datetime.now()
    hour_slot = now.hour // 6
    return LENGTH_MODES[hour_slot % 2]


def load_performance_feedback() -> str:
    """
    Read performance_log.json and build a prompt section that tells the AI
    which hook styles / CTAs underperformed so it avoids repeating them.
    """
    if not os.path.exists(PERFORMANCE_LOG):
        return ""

    try:
        with open(PERFORMANCE_LOG, "r") as f:
            log_data = json.load(f)

        entries = log_data.get("videos", [])
        if len(entries) < 5:
            return ""  # Not enough data yet

        # Calculate average views
        views_list = [e.get("views", 0) for e in entries if e.get("views", 0) > 0]
        if not views_list:
            return ""

        avg_views = sum(views_list) / len(views_list)

        # Find underperformers (less than 50% of average)
        underperformers = [
            e for e in entries
            if e.get("views", 0) > 0 and e.get("views", 0) < avg_views * 0.5
        ]

        # Find top performers (more than 150% of average)
        top_performers = [
            e for e in entries
            if e.get("views", 0) > avg_views * 1.5
        ]

        if not underperformers and not top_performers:
            return ""

        feedback_lines = ["\n\nPERFORMANCE DATA FROM THIS CHANNEL (use this to improve):"]

        if top_performers:
            feedback_lines.append("HIGH PERFORMERS (replicate these patterns):")
            for v in top_performers[-5:]:
                feedback_lines.append(
                    f"  - '{v.get('title','')}' | {v.get('views',0):,} views | "
                    f"hook_type: {v.get('hook_type','?')} | cta_type: {v.get('cta_type','?')}"
                )

        if underperformers:
            feedback_lines.append("AVOID THESE PATTERNS (underperformed):")
            for v in underperformers[-5:]:
                feedback_lines.append(
                    f"  - '{v.get('title','')}' | {v.get('views',0):,} views | "
                    f"hook_type: {v.get('hook_type','?')} | cta_type: {v.get('cta_type','?')}"
                )

        return "\n".join(feedback_lines)

    except Exception as e:
        log.warning(f"Could not load performance feedback: {e}")
        return ""


def build_prompt(count: int, subniche: str, used_animals: list[str], length_mode: str = "long") -> str:
    exclusion = build_exclusion_prompt(used_animals)
    performance_feedback = load_performance_feedback()

    if length_mode == "short":
        length_instructions = """
═══════════════════════════════════════
TARGET: SHORT FORMAT — 38–42 words TOTAL. Spoken in exactly 13 seconds.
This is the highest-completion-rate format on Shorts. One fact. One CTA. Done.
FORMAT: hook (10–12 words) + one shocking fact (18–20 words) + cta (8–10 words)
═══════════════════════════════════════"""
    else:
        length_instructions = """
═══════════════════════════════════════
TARGET: LONG FORMAT — 170–180 words TOTAL. Spoken in exactly 55–60 seconds.
This maximises engaged view time and ad revenue signals.
FORMAT: hook (15–20 words) + 3 escalating facts (120–130 words) + cta (15–20 words)
Each fact must be MORE surprising than the last. Build to a climax.
═══════════════════════════════════════"""

    return f"""You are a viral YouTube Shorts writer. You write like a hyped-up friend texting wild animal facts — casual, punchy, zero fluff. Generate {count} scripts about: "{subniche}"
{exclusion}
{performance_feedback}
{length_instructions}

CRITICAL 2025/26 ALGORITHM FACTS:
1. COMPLETION RATE is king — if they watch to the end, you win
2. SHARES are the #1 viral signal — write something people HAVE to send to a friend
3. REPLAYS boost rank dramatically — loop hook must make viewer feel they missed something
4. ENGAGED VIEWS > raw views — the hook must physically stop someone from swiping

PUNCTUATION RULES (TTS voice uses these for natural pauses):
- Use "..." before the craziest reveal
- Use "—" for mid-sentence pivots
- Use "!" for energy peaks — max 2 per script
- Never end a sentence flatly if it can end with a punch

HOOK FORMULA (first 2 seconds decides everything):
Pick ONE format:
1. WRONG FACT OPENER: Start with something impossible, then confirm it's real
2. SCALE SHOCK: "This [animal] can [action] — that's like a human [relatable comparison]"
3. VS BATTLE: "[Animal] vs [thing 10x bigger]. It wins. Every. Single. Time."
4. CHAOS NORMAL: State the most insane fact as if it's totally boring news

CTA STRATEGY (pick one per script, rotate):
TYPE A — DEBATE BAIT: "Comment [X] or [Y]. No in between."
TYPE B — SHARE BAIT: "Send this to someone who'd never believe it."
TYPE C — CHALLENGE: "Name ONE animal tougher than this. I'll wait."
TYPE D — WRONG ANSWERS: "Wrong answers only — what would you do against this thing?"

PINNED COMMENT (this goes as the first pinned comment after upload):
- Must be a QUESTION that triggers argument or debate in the replies
- Should directly relate to the video's main fact
- 1 sentence, conversational, under 15 words
- Example: "Could you survive 3 minutes with this thing? Be honest."

NICHE SEO TAGS (5–7 ANIMAL-SPECIFIC hashtags for this exact animal):
- NOT generic tags like #Animals #Wildlife
- SPECIFIC to the animal: e.g. for mantis shrimp → #mantisshrimp #pistolshrimp #oceancreature #sealife #marinelife #underwaterworld
- Include the animal name as a hashtag
- Include the animal's habitat/type as hashtags
- Think: what would someone search to find videos about THIS specific animal?

LOOP HOOK (last 3.5 seconds — makes viewer feel they missed something):
- Reference a SPECIFIC moment in the video
- NOT generic "watch again"
- Examples: "Rewatch the decibel number. It still doesn't make sense."

Respond ONLY with valid JSON array. No markdown. Start with [

[
  {{
    "title": "Unhinged title under 55 chars — sounds impossible but true #Shorts",
    "animal_keyword": "single animal name for Pexels video search",
    "length_mode": "{length_mode}",
    "hook": "Hook text — stops the swipe. Uses punctuation for drama.",
    "body": "Body — ONE comparison, ONE '... wait for it ...' beat. Conversational.",
    "cta": "One of TYPE A/B/C/D above. 8–12 words MAX.",
    "tags": ["#Shorts", "#AnimalFacts", "#Animals", "#Wildlife"],
    "seo_tags": ["#specificanimal", "#habitat", "#animaltype", "#niche1", "#niche2"],
    "emoji": "most chaotic relevant emoji",
    "shock_word": "ONE all-caps word e.g. IMPOSSIBLE / INSANE / WAIT / NOPE / WILD",
    "loop_hook": "6–9 words referencing a SPECIFIC moment in THIS video",
    "pinned_comment": "One debate question under 15 words for pinned comment",
    "hook_type": "wrong_fact | scale_shock | vs_battle | chaos_normal",
    "cta_type": "A | B | C | D"
  }}
]

TONE — copy this energy exactly:
BAD hook: "The mantis shrimp has a very powerful punch that scientists have studied."
GOOD hook: "This shrimp punches so fast... it literally boils the water. Yes. Really."

BAD cta: "Follow for more amazing animal facts every day!"
GOOD cta: "Send this to someone who needs to know shrimp are terrifying."

BAD loop_hook: "Watch this video again for more facts."
GOOD loop_hook: "Rewatch the decibel number. It still doesn't make sense."

BAD pinned_comment: "What do you think of this animal?"
GOOD pinned_comment: "Could a mantis shrimp punch through your hand? Be honest."

FINAL RULES:
- All facts must be 100% accurate with real numbers
- Every animal must be different from others in this batch
- No visual references ("as you can see") — audio only
- No tongue-twisters or awkward phrasing"""


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


def validate_scripts(scripts: list, length_mode: str) -> list:
    fixed = []
    for s in scripts:
        full_text = f"{s.get('hook','')} {s.get('body','')} {s.get('cta','')}"
        word_count = len(full_text.split())

        if length_mode == "short":
            min_words, max_words = 32, 48
        else:
            min_words, max_words = 155, 195

        log.info(f"Script '{s.get('title','?')}' — {word_count} words — mode: {length_mode}")

        if word_count < min_words:
            log.warning(f"Too short ({word_count} words) — padding")
            s['body'] = s.get('body', '') + " Scientists are still figuring out how this is even possible."
        elif word_count > max_words:
            log.warning(f"Too long ({word_count} words) — trimming")
            body_words = s.get('body', '').split()
            trim_to = 100 if length_mode == "long" else 25
            s['body'] = " ".join(body_words[:trim_to])

        if not s.get('shock_word'):
            s['shock_word'] = 'WAIT'

        if not s.get('loop_hook'):
            s['loop_hook'] = "Wait... did you catch that detail?"

        # Ensure loop_hook is specific, not generic
        generic_hooks = ["watch again", "watch this again", "watch more", "see more"]
        if any(g in s.get('loop_hook', '').lower() for g in generic_hooks):
            animal = s.get('animal_keyword', 'this animal')
            s['loop_hook'] = f"Rewatch the part about the {animal}. Still insane."

        if not s.get('pinned_comment'):
            animal = s.get('animal_keyword', 'this animal')
            s['pinned_comment'] = f"Could you survive 60 seconds with a {animal}? Be honest."

        if not s.get('seo_tags'):
            animal = s.get('animal_keyword', 'animal').lower().replace(' ', '')
            s['seo_tags'] = [f"#{animal}", "#wildlife", "#nature", "#animalkingdom", "#wildanimals"]

        if not s.get('hook_type'):
            s['hook_type'] = 'wrong_fact'

        if not s.get('cta_type'):
            s['cta_type'] = 'B'

        s['length_mode'] = length_mode
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
        "temperature": 0.88,
        "max_tokens": 4000,
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
    length_mode = get_length_mode()
    log.info(f"Sub-niche this slot: {subniche}")
    log.info(f"Length mode: {length_mode} ({'13s' if length_mode == 'short' else '55-60s'})")

    used_animals = get_used_animals()
    log.info(f"Animals used so far: {len(used_animals)} — {used_animals[-5:] if used_animals else 'none yet'}")

    prompt = build_prompt(count, subniche, used_animals, length_mode)

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

    scripts = validate_scripts(scripts, length_mode)

    new_animals = [s.get("animal_keyword", "").lower().strip() for s in scripts if s.get("animal_keyword")]
    mark_animals_used(new_animals)
    log.info(f"Marked {len(new_animals)} new animals as used: {new_animals}")

    log.info(f"Generated {len(scripts)} scripts via AI (free)")
    return scripts
