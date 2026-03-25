"""
Script Generator — uses Groq API (100% FREE).

UPDATES v2.1:
- LOOP-BACK SYNTAX: Forces the AI to write the final sentence as a 'cliffhanger' 
  that is only resolved by the first word of the hook (Involuntary Replays).
- RETENTION PUNCH: Added 'Wait' and 'Nope' markers to body text to prevent mid-video swipes.
- DYNAMIC HOOKS: Rotates Hook Formulas to prevent 'Automation Fatigue'.
- GROQ SAFETY: Added exponential backoff retry loop for Groq 429 Rate Limits.
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

LENGTH_MODES = ["short", "short", "long", "long"] 


def get_todays_subniche() -> str:
    now = datetime.now()
    hour_slot = now.hour // 6
    index = (now.timetuple().tm_yday * 4 + hour_slot) % len(SUBNICHES)
    return SUBNICHES[index]


def get_length_mode() -> str:
    now = datetime.now()
    hour_slot = now.hour // 6
    return LENGTH_MODES[hour_slot % len(LENGTH_MODES)]


def load_performance_feedback() -> str:
    if not os.path.exists(PERFORMANCE_LOG):
        return ""

    try:
        with open(PERFORMANCE_LOG, "r") as f:
            log_data = json.load(f)

        entries = log_data.get("videos", [])
        if len(entries) < 5:
            return ""

        def get_score(e):
            evr = e.get("engaged_view_rate", 0)
            if evr > 0: return evr
            return e.get("views", 0) / 100000

        scores = [get_score(e) for e in entries if get_score(e) > 0]
        if not scores: return ""

        avg_score = sum(scores) / len(scores)

        # Aggressive filtering: find what really worked vs what failed
        underperformers = [e for e in entries if get_score(e) > 0 and get_score(e) < avg_score * 0.5]
        top_performers = [e for e in entries if get_score(e) > avg_score * 1.5]

        feedback_lines = ["\n\nALGORITHM FEEDBACK LOOP:"]

        if top_performers:
            feedback_lines.append("VIRAL PATTERNS (REPLICATE):")
            for v in top_performers[-3:]:
                feedback_lines.append(f" - {v.get('title','')} (EVR: {v.get('engaged_view_rate', 0):.1%})")

        if underperformers:
            feedback_lines.append("SWIPE-AWAY PATTERNS (AVOID):")
            for v in underperformers[-3:]:
                feedback_lines.append(f" - {v.get('title','')} (EVR: {v.get('engaged_view_rate', 0):.1%})")

        return "\n".join(feedback_lines)
    except Exception as e:
        log.warning(f"Feedback error: {e}")
        return ""


def build_prompt(count: int, subniche: str, used_animals: list[str], length_mode: str = "long") -> str:
    exclusion = build_exclusion_prompt(used_animals)
    performance_feedback = load_performance_feedback()

    # Viral Constraint: 13s videos need to be extremely punchy
    if length_mode == "short":
        length_instructions = """
TARGET: 13-SECOND 'ULTRA-SHORT' (38-42 words).
- Aim for 100% completion. 
- The loop MUST be seamless: the end of the CTA must lead into the first word of the hook."""
    else:
        length_instructions = """
TARGET: 55-60 SECOND 'DEEP-DIVE' (170-180 words).
- Focus on 'Escalating Stakes': Fact 1 is weird, Fact 2 is scary, Fact 3 is impossible."""

    return f"""You are a master of YouTube Shorts virality. Write {count} scripts about "{subniche}".
{exclusion}
{performance_feedback}
{length_instructions}

VIRAL RULES:
1. THE INVOLUNTARY REPLAY: The script ends with a setup that the hook resolves.
2. NO 'AS YOU CAN SEE': Audio-only engagement.
3. TYPE B CTA: Focus on 'Shareability'. "Send this to someone who..."
4. PATTERN INTERRUPTS: Use words like 'Wait...', 'Nope.', or 'Actually...' in the body.

Respond ONLY with JSON.

[
  {{
    "title": "Title with curiosity gap #Shorts",
    "animal_keyword": "animal name",
    "length_mode": "{length_mode}",
    "hook": "Must stop the swipe in 1.5 seconds.",
    "body": "Fast paced. Use '...' for dramatic pauses.",
    "cta": "TYPE B focus (Share Bait).",
    "shock_word": "ONE all-caps word e.g. IMPOSSIBLE / INSANE / WAIT",
    "loop_hook": "How the CTA connects back to the hook",
    "hook_type": "wrong_fact | scale_shock | vs_battle | chaos_normal",
    "cta_type": "B",
    "seo_tags": ["#tag1", "#tag2", "#tag3"]
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


def validate_scripts(scripts: list, length_mode: str) -> list:
    """Enforces safety constraints and Viral Loop connections if the AI misses them."""
    fixed = []
    for s in scripts:
        if not s.get('shock_word'):
            s['shock_word'] = 'WAIT'
            
        # VIRAL REFINEMENT: Force the Loop Connection
        if not s.get('loop_hook') or len(s.get('loop_hook', '').split()) < 3:
            s['loop_hook'] = f"Wait... did you catch that? Look at the {s.get('animal_keyword', 'animal')} again."

        # Ensure SEO tags exist
        if not s.get('seo_tags'):
            animal_tag = s.get('animal_keyword', 'animal').replace(' ', '').lower()
            s['seo_tags'] = [f"#{animal_tag}", "#wildlife", "#shorts"]

        s['length_mode'] = length_mode
        fixed.append(s)
    return fixed


async def _try_groq(prompt: str) -> list:
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    body = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.88,
        "max_tokens": 4000,
    }
    
    # VIRAL FIX: Exponential backoff for Groq Rate Limits
    for attempt in range(3):
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(GROQ_URL, headers=headers, json=body)
            
        if resp.status_code == 429:
            wait_time = 60 * (attempt + 1)
            log.warning(f"Groq API Rate Limit (429) hit! Pausing for {wait_time}s before retry...")
            await asyncio.sleep(wait_time)
            continue
            
        resp.raise_for_status()
        return parse_json(resp.json()["choices"][0]["message"]["content"])
        
    raise RuntimeError("Groq rate limit exhausted after 3 attempts.")


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
        return parse_json(resp.json()["candidates"][0]["content"]["parts"][0]["text"])
        
    raise RuntimeError("Gemini quota exhausted")


async def generate_scripts(count: int = 1) -> list[dict]:
    if not GROQ_API_KEY and not GEMINI_API_KEY:
        raise ValueError("No API key found! Add GROQ_API_KEY=gsk_xxx (free at console.groq.com)")

    subniche = get_todays_subniche()
    length_mode = get_length_mode()
    log.info(f"Sub-niche: {subniche}")
    log.info(f"Length mode: {length_mode} ({'13s' if length_mode == 'short' else '55-60s'})")

    used_animals = get_used_animals()
    log.info(f"Animals used so far: {len(used_animals)}")

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
    log.info(f"Generated {len(scripts)} scripts")
    
    return scripts
