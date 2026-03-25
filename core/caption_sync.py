"""
Caption Sync v3.1 — generates word-level timing data from Edge-TTS boundary events.
UPDATED: Implements rapid-fire, single/double word dynamic coloring (Hormozi-style)
using 100% free FFmpeg drawtext filters.

FIXES v3.1:
- _estimate_timings is now a top-level function (was already, confirmed importable).
- get_word_timings now explicitly falls back to _estimate_timings when boundary
  capture succeeds but returns an empty list (edge-tts v7 event name change).
- build_caption_drawtext: fixed fallback filter from "copy" (invalid for video
  filtergraph) to "null" which is the correct FFmpeg video passthrough filter.
"""

import asyncio
import logging

log = logging.getLogger(__name__)

TICKS_PER_SECOND = 10_000_000

async def get_word_timings(text: str, voice: str = "en-US-BrianNeural") -> list[dict]:
    try:
        timings = await _capture_boundaries(text, voice)
        if timings:
            return timings
        # Boundary capture succeeded but returned nothing — use estimate
        log.warning("Boundary capture returned empty list — falling back to estimate")
        return _estimate_timings(text)
    except Exception as e:
        log.warning(f"Word boundary capture failed: {e} — falling back to estimate timing")
        return _estimate_timings(text)

async def _capture_boundaries(text: str, voice: str) -> list[dict]:
    import edge_tts
    communicate = edge_tts.Communicate(text=text, voice=voice, rate="+8%", volume="+0%", pitch="+0Hz")
    boundaries = []
    async for event in communicate.stream():
        # FIX v3.1: handle both edge-tts v6 ("WordBoundary") and v7 ("word_boundary")
        if event["type"] in ("WordBoundary", "word_boundary"):
            start_sec    = event["offset"] / TICKS_PER_SECOND
            duration_sec = event["duration"] / TICKS_PER_SECOND
            # FIX v3.1: v7 uses "word" key, v6 uses "text" key
            word = event.get("text", event.get("word", "")).strip()
            if word:
                boundaries.append({
                    "word":  word.upper(),
                    "start": round(start_sec, 3),
                    "end":   round(start_sec + duration_sec, 3),
                })
    if not boundaries:
        raise ValueError("No WordBoundary events received")
    return boundaries

def _estimate_timings(text: str, words_per_second: float = 2.8) -> list[dict]:
    """
    Fallback: estimate word timings from text alone when TTS boundary events fail.
    Exported at module level so tts_engine.py can import it directly.
    """
    words = [w for w in text.upper().split() if w]
    timings, t = [], 0.5
    for word in words:
        duration = max(0.2, len(word) * 0.055)
        timings.append({"word": word, "start": round(t, 3), "end": round(t + duration, 3)})
        t += duration + 0.05
    return timings

def group_into_chunks(timings: list[dict], chunk_size: int = 1) -> list[dict]:
    """
    VIRAL UPDATE: Default chunk_size=1.
    One word on screen at a time creates maximum visual pacing.
    """
    chunks, i = [], 0
    while i < len(timings):
        group = timings[i:i + chunk_size]
        text  = " ".join(w["word"] for w in group)
        chunks.append({"text": text, "start": group[0]["start"], "end": group[-1]["end"]})
        i += chunk_size
    return chunks

def build_caption_drawtext(
    chunks: list[dict],
    font_path: str,
    video_h: int = 1280,
    video_w: int = 720,
) -> str:
    """
    VIRAL UPDATE: Dynamic coloring — every 3rd/4th word or long/impactful word
    is highlighted in #FFE600 (Viral Yellow).

    FIX v3.1: returns "null" (valid FFmpeg video passthrough) instead of "copy"
    when chunks is empty. "copy" is only valid in -c:v context, not filtergraphs.
    """
    if not chunks:
        return "null"

    font_arg = f":fontfile='{font_path.replace(chr(92), '/')}'" if font_path else ""
    filters  = []

    for idx, chunk in enumerate(chunks):
        safe = (
            chunk["text"]
            .replace("'", "")
            .replace(":", "")
            .replace(",", "")
            .replace("\\", "")
            .replace('"', "")
        )
        t_start = chunk["start"]
        t_end   = chunk["end"] + 0.08  # Slight tail for smoother reading

        # Highlight logic: colour long words or alternating beats yellow
        is_highlight = len(safe) > 6 or idx % 4 == 0
        font_color   = "#FFE600" if is_highlight else "white"
        font_size    = "90" if is_highlight else "80"

        char_count   = len(safe)
        est_text_w   = min(char_count * 50, video_w - 40)
        box_x        = int((video_w - est_text_w) / 2) - 20
        box_w        = est_text_w + 40
        box_y        = int(video_h * 0.58) - 10
        box_h        = 100

        filters.append(
            f"drawbox=x={box_x}:y={box_y}:w={box_w}:h={box_h}"
            f":color=black@0.40:t=fill"
            f":enable='between(t,{t_start:.3f},{t_end:.3f})'"
        )
        filters.append(
            f"drawtext=text='{safe}'{font_arg}"
            f":fontsize={font_size}:fontcolor={font_color}"
            f":borderw=6:bordercolor=black"
            f":x=(w-text_w)/2:y=(h-text_h)/2+100"
            f":enable='between(t,{t_start:.3f},{t_end:.3f})'"
        )

    return ",".join(filters)
