"""
Script Generator — uses Groq API (100% FREE).

UPDATES v2.1:
- LOOP-BACK SYNTAX: Forces the AI to write the final sentence as a 'cliffhanger' 
  that is only resolved by the first word of the hook (Involuntary Replays).
- RETENTION PUNCH: Added 'Wait' and 'Nope' markers to body text to prevent mid-video swipes.
- DYNAMIC HOOKS: Rotates Hook Formulas to prevent 'Automation Fatigue'.
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
    "loop_hook": "How the CTA connects back to the hook",
    "hook_type": "wrong_fact | scale_shock | vs_battle | chaos_normal",
    "cta_type": "B"
  }}
]"""

# ... [parse_json, validate_scripts, and generate_scripts remain standard] ...
