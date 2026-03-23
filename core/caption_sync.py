"""
Caption Sync — generates word-level timing data from Edge-TTS boundary events.

WHY THIS EXISTS:
Edge-TTS emits WordBoundary events during synthesis that give us the exact
start offset (in 100-nanosecond ticks) for every spoken word. We capture
these and convert them to seconds, giving us frame-accurate caption sync.

85% of Shorts viewers watch muted. Captions that drift even 0.3s behind
the voice are a direct swipe-away trigger. This module eliminates drift.

OUTPUT FORMAT:
[
  {"word": "THIS", "start": 0.0,  "end": 0.52},
  {"word": "SHRIMP", "start": 0.52, "end": 1.10},
  ...
]

These timings are used by video_assembler.py to replace the old
estimate-based drawtext timing with exact per-word overlays.
"""

import asyncio
import logging
import re

log = logging.getLogger(__name__)

# 100-nanosecond ticks per second (Edge-TTS uses Windows FILETIME units)
TICKS_PER_SECOND = 10_000_000


async def get_word_timings(text: str, voice: str = "en-US-BrianNeural") -> list[dict]:
    """
    Run Edge-TTS synthesis and capture WordBoundary events.

    Returns list of {word, start, end} dicts with times in seconds.
    Falls back to estimate-based timing if edge-tts boundary capture fails.
    """
    try:
        return await _capture_boundaries(text, voice)
    except Exception as e:
        log.warning(f"Word boundary capture failed: {e} — falling back to estimate timing")
        return _estimate_timings(text)


async def _capture_boundaries(text: str, voice: str) -> list[dict]:
    import edge_tts

    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate="+8%",
        volume="+0%",
        pitch="+0Hz"
    )

    boundaries = []

    # Iterate over the stream and collect WordBoundary events
    async for event in communicate.stream():
        if event["type"] == "WordBoundary":
            # offset is in 100-nanosecond ticks
            start_sec = event["offset"] / TICKS_PER_SECOND
            duration_sec = event["duration"] / TICKS_PER_SECOND
            word = event.get("text", "").strip()
            if word:
                boundaries.append({
                    "word": word.upper(),
                    "start": round(start_sec, 3),
                    "end": round(start_sec + duration_sec, 3),
                })

    if not boundaries:
        raise ValueError("No WordBoundary events received")

    log.info(f"Captured {len(boundaries)} word boundaries")
    return boundaries


def _estimate_timings(text: str, words_per_second: float = 2.8) -> list[dict]:
    """
    Fallback: estimate timing based on average speaking rate.
    2.8 words/second matches Edge-TTS BrianNeural at +8% rate.
    """
    words = [w for w in text.upper().split() if w]
    timings = []
    t = 0.5  # small lead-in before first word

    for word in words:
        # Longer words take slightly longer
        duration = max(0.2, len(word) * 0.055)
        timings.append({
            "word": word,
            "start": round(t, 3),
            "end": round(t + duration, 3),
        })
        t += duration + 0.05  # small gap between words

    log.info(f"Estimated timings for {len(timings)} words")
    return timings


def group_into_chunks(timings: list[dict], chunk_size: int = 2) -> list[dict]:
    """
    Group word timings into 2-word caption chunks.
    Returns list of {text, start, end} dicts.

    chunk_size=2 is the viral sweet spot — fast enough to feel energetic,
    slow enough to be readable on a moving commute.
    """
    chunks = []
    i = 0
    while i < len(timings):
        group = timings[i:i + chunk_size]
        text = " ".join(w["word"] for w in group)
        start = group[0]["start"]
        end = group[-1]["end"]
        chunks.append({
            "text": text,
            "start": start,
            "end": end,
        })
        i += chunk_size

    return chunks


def build_caption_drawtext(chunks: list[dict], font_path: str, video_h: int = 1280, video_w: int = 720) -> str:
    """
    Build FFmpeg drawtext + drawbox filter string from synced caption chunks.

    Each chunk gets:
    1. A semi-transparent black pill background (drawbox)
    2. White bold caption text on top (drawtext)

    Both use exact start/end times from word boundary data.
    """
    if not chunks:
        return "null"

    font_arg = f":fontfile='{font_path.replace(chr(92), '/')}'" if font_path else ""
    filters = []

    for chunk in chunks:
        safe = (chunk["text"]
                .replace("'", "")
                .replace(":", "")
                .replace(",", "")
                .replace("\\", "")
                .replace('"', ""))

        t_start = chunk["start"]
        t_end = chunk["end"] + 0.05  # tiny tail so last word doesn't flash off

        char_count = len(safe)
        est_text_w = min(char_count * 44, video_w - 40)
        box_x = int((video_w - est_text_w) / 2) - 20
        box_w = est_text_w + 40
        box_y = int(video_h * 0.58) - 8
        box_h = 82

        # Background pill
        filters.append(
            f"drawbox=x={box_x}:y={box_y}:w={box_w}:h={box_h}"
            f":color=black@0.60:t=fill"
            f":enable='between(t,{t_start:.3f},{t_end:.3f})'"
        )

        # Caption text
        filters.append(
            f"drawtext=text='{safe}'"
            f"{font_arg}"
            f":fontsize=72"
            f":fontcolor=white"
            f":borderw=4:bordercolor=black"
            f":x=(w-text_w)/2:y=h*0.60"
            f":enable='between(t,{t_start:.3f},{t_end:.3f})'"
        )

    return ",".join(filters)
