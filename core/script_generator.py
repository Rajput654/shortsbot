"""
Script Generator — uses Groq API (100% FREE).
Produces 35-40 second scripts (90-100 words).
Tracks used animals and never repeats them.
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
    day_index = datetime.now().timetuple().tm_yday % len(SUBNICHES)
    return SUBNICHES[day_index]

def build_prompt(count: int, subniche: str, used_animals: list[str]) -> str:
    exclusion = build_exclusion_prompt(used_animals)
    return f"""You are a viral YouTube Shorts writer with the humor of a stand-up comedian and the knowledge of a wildlife documentary. Generate {count} scripts about: "{subniche}"
{exclusion}

TARGET: 90-100 words total per script. 35-40 seconds spoken aloud. ZERO FLUFF.

COMEDY RULES (non-negotiable):
- Write like you are texting your funniest friend, not reading a textbook
- Use casual language: "this thing", "absolutely unhinged", "for no reason", "built different"
- Add ONE funny comparison (e.g. "that is like a human punching through a concrete wall")
- Include a WAIT FOR IT beat before the craziest fact
- The hook must cause physical discomfort to skip

Hook styles (rotate through these):
1. Fake-out: Start with something that sounds wrong, then confirm it is true
2. Scale shock: Compare the animal ability to something humans can relate to
3. Chaos opener: Lead with the wildest fact as if it is totally normal
4. Vs battle: "This animal vs something 10x bigger and it wins every time"

Respond ONLY with valid JSON array. No markdown. Start with [

[
  {{
    "title": "Catchy title under 60 chars, make it sound unhinged #Shorts",
    "animal_keyword": "single animal name for video search",
    "hook": "1-2 sentences. MUST be shocking or funny. 20-25 words. No hedging.",
    "body": "3-4 sentences. Include ONE funny comparison. Use casual tone. Include a WAIT FOR IT beat before the craziest fact. 55-65 words.",
    "cta": "Funny CTA, NOT just follow for more. Make it specific. 10-15 words.",
    "tags": ["#Shorts", "#AnimalFacts", "#Wildlife", "#Animals"],
    "emoji": "most chaotic relevant emoji",
    "shock_word": "ONE all-caps word for giant text overlay at hook peak e.g. IMPOSSIBLE or INSANE or WAIT"
  }}
]

TONE EXAMPLES (copy this energy):
BAD: "The mantis shrimp has a powerful punch that scientists have studied."
GOOD: "This shrimp punches so fast it literally boils the water around its fist. Yes, really."

BAD: "Follow for more animal facts!"
GOOD: "Comment the animal you thought was toughest. You were wrong."

Rules:
- hook + body + cta = 90-100 words
- Every animal different from each other
- ALL facts must be 100 percent accurate with real numbers
- Conversational, sounds natural when read aloud fast
- No visual references, audio only"""

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

        if word_count < 80:
            log.warning(f"Too short ({word_count} words) — padding")
            s['body'] = s.get('body', '') + (
                " Scientists continue to study this amazing creature every year."
                " Each new discovery reveals just how extraordinary nature truly is."
            )
        elif word_count > 115:
            log.warning(f"Too long ({word_count} words) — trimming")
            body_words = s.get('body', '').split()
            s['body'] = " ".join(body_words[:60])

        # Ensure shock_word exists
        if not s.get('shock_word'):
            s['shock_word'] = 'WAIT'

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
        "temperature": 0.85,
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
        "generationConfig": {"temperature": 0.85, "maxOutputTokens": 3000}
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

async def generate_scripts(count: int = 4) -> list[dict]:
    if not GROQ_API_KEY and not GEMINI_API_KEY:
        raise ValueError(
            "No API key found!\n"
            "Add GROQ_API_KEY=gsk_xxx (free at console.groq.com)"
        )

    subniche = get_todays_subniche()
    log.info(f"Sub-niche today: {subniche}")

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
