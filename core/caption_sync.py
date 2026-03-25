"""
Caption Sync v4.0 — Scenario Text Overlay System

COMPLETE REWRITE v4.0:
- FROM: Word-by-word TTS captions
- TO: Big scenario text overlays that DRIVE THE STORY

This is the core of what makes viral animal shorts work.
The text on screen IS the joke — not a subtitle.

OVERLAY STYLES:
- pov_header:       Big centered text "POV: You're the dog" — white, huge
- setup:            Normal story setup text — white, medium
- escalate:         Building tension — yellow, medium, slight bounce
- reaction_setup:   "The cat:" or "The dog:" — sets up the punchline
- punchline:        BIGGEST text, yellow/red, ALL CAPS or emoji
- aftermath:        Post-punchline fallout — smaller, italic-style
- loop_close:       Loop-back text at end — white, medium
- cta:              Share bait CTA — white with arrow emoji

ALSO RETAINS:
- _estimate_timings() for TTS word boundary fallback
- group_into_chunks() for voice_line caption display (if voice used)
"""

import logging
import re

log = logging.getLogger(__name__)


# ── STYLE DEFINITIONS ─────────────────────────────────────────────────────────
# Each style defines: fontsize, fontcolor, bg_color, bg_opacity, position_y_pct,
# border_color, border_width, duration_extra (seconds added beyond beat window)

OVERLAY_STYLES = {
    "pov_header": {
        "fontsize": 68,
        "fontcolor": "white",
        "bg_color": "black",
        "bg_opacity": 0.75,
        "position_y_pct": 0.12,   # Top area
        "border_color": "black",
        "border_width": 5,
        "padding_x": 30,
        "padding_y": 18,
    },
    "setup": {
        "fontsize": 62,
        "fontcolor": "white",
        "bg_color": "black",
        "bg_opacity": 0.60,
        "position_y_pct": 0.55,
        "border_color": "black",
        "border_width": 5,
        "padding_x": 28,
        "padding_y": 15,
    },
    "escalate": {
        "fontsize": 65,
        "fontcolor": "#FFE600",    # Viral Yellow
        "bg_color": "black",
        "bg_opacity": 0.65,
        "position_y_pct": 0.55,
        "border_color": "black",
        "border_width": 6,
        "padding_x": 28,
        "padding_y": 15,
    },
    "reaction_setup": {
        "fontsize": 58,
        "fontcolor": "white",
        "bg_color": "black",
        "bg_opacity": 0.55,
        "position_y_pct": 0.60,
        "border_color": "black",
        "border_width": 4,
        "padding_x": 25,
        "padding_y": 12,
    },
    "punchline": {
        "fontsize": 80,            # BIGGEST — this is the joke payoff
        "fontcolor": "#FFE600",
        "bg_color": "black",
        "bg_opacity": 0.80,
        "position_y_pct": 0.52,
        "border_color": "black",
        "border_width": 8,
        "padding_x": 35,
        "padding_y": 20,
    },
    "aftermath": {
        "fontsize": 55,
        "fontcolor": "#DDDDDD",
        "bg_color": "black",
        "bg_opacity": 0.50,
        "position_y_pct": 0.62,
        "border_color": "black",
        "border_width": 4,
        "padding_x": 22,
        "padding_y": 12,
    },
    "loop_close": {
        "fontsize": 60,
        "fontcolor": "white",
        "bg_color": "black",
        "bg_opacity": 0.60,
        "position_y_pct": 0.55,
        "border_color": "black",
        "border_width": 5,
        "padding_x": 28,
        "padding_y": 14,
    },
    "cta": {
        "fontsize": 58,
        "fontcolor": "white",
        "bg_color": "black",
        "bg_opacity": 0.70,
        "position_y_pct": 0.78,   # Lower — CTA at bottom
        "border_color": "black",
        "border_width": 5,
        "padding_x": 28,
        "padding_y": 14,
    },
}

# Default fallback style
DEFAULT_STYLE = OVERLAY_STYLES["setup"]


def _sanitize_text(text: str) -> str:
    """
    Sanitize overlay text for FFmpeg drawtext.
    Remove chars that break FFmpeg filter syntax.
    Handle multi-line via \\n for FFmpeg.
    """
    # Remove chars that break FFmpeg drawtext
    text = text.replace("'", "").replace('"', "").replace("\\", "")
    text = text.replace(":", " ").replace(";", "")

    # Convert *action text* to (action text)
    text = re.sub(r'\*([^*]+)\*', r'(\1)', text)

    # Handle newlines - FFmpeg drawtext uses \n
    text = text.replace("\n", "\\n")

    # Collapse multiple spaces
    text = re.sub(r'  +', ' ', text).strip()

    # Truncate very long lines — wrap at ~30 chars
    if len(text) > 35 and "\\n" not in text:
        words = text.split()
        lines = []
        current = []
        for word in words:
            if sum(len(w) + 1 for w in current) + len(word) > 28:
                if current:
                    lines.append(" ".join(current))
                    current = [word]
                else:
                    lines.append(word)
            else:
                current.append(word)
        if current:
            lines.append(" ".join(current))
        text = "\\n".join(lines)

    return text


def build_scenario_overlays(
    scene_beats: list[dict],
    font_path: str,
    video_h: int = 1280,
    video_w: int = 720,
    total_duration: float = 0.0,
) -> str:
    """
    Build FFmpeg filter_complex drawtext filters for all scene beats.

    Each beat gets:
    1. A semi-transparent background box
    2. The overlay text in the appropriate style

    Returns the filter string to inject into filter_complex.
    Returns "null" if no beats (FFmpeg passthrough).
    """
    if not scene_beats:
        return "null"

    font_arg = f":fontfile='{font_path.replace(chr(92), '/')}'" if font_path else ""
    filters = []

    for i, beat in enumerate(scene_beats):
        text = beat.get("overlay_text", "").strip()
        if not text:
            continue

        style_name = beat.get("style", "setup")
        style = OVERLAY_STYLES.get(style_name, DEFAULT_STYLE)

        t_start = float(beat.get("timestamp", 0.0))

        # End time = next beat's timestamp - 0.1s gap, or total_duration
        if i + 1 < len(scene_beats):
            t_end = float(scene_beats[i + 1].get("timestamp", t_start + 3.0)) - 0.08
        else:
            t_end = total_duration if total_duration > t_start else t_start + 4.0

        # Minimum display time = 1.2s
        if t_end - t_start < 1.2:
            t_end = t_start + 1.2

        safe_text = _sanitize_text(text)
        if not safe_text:
            continue

        # Calculate position
        y_pos = int(video_h * style["position_y_pct"])
        fontsize = style["fontsize"]
        pad_x = style["padding_x"]
        pad_y = style["padding_y"]
        bg_opacity = style["bg_opacity"]
        bg_color = style["bg_color"]
        fontcolor = style["fontcolor"]
        border_w = style["border_width"]
        border_color = style["border_color"]

        # Estimate text dimensions for background box
        # (FFmpeg doesn't expose text_w until render — we estimate)
        lines = safe_text.split("\\n")
        max_line_len = max(len(l) for l in lines)
        num_lines = len(lines)

        # Rough char width = fontsize * 0.55
        est_text_w = min(int(max_line_len * fontsize * 0.54), video_w - 40)
        est_text_h = int(num_lines * fontsize * 1.15)

        box_w = est_text_w + pad_x * 2
        box_h = est_text_h + pad_y * 2
        box_x = max(0, int((video_w - box_w) / 2))
        box_y = max(0, y_pos - pad_y)

        # Clamp to screen
        box_w = min(box_w, video_w - box_x - 2)
        box_h = min(box_h, video_h - box_y - 2)

        enable = f"between(t,{t_start:.3f},{t_end:.3f})"

        # Background box
        # Convert hex color to FFmpeg format if needed
        ffmpeg_bg = _hex_to_ffmpeg_color(bg_color, bg_opacity)

        filters.append(
            f"drawbox=x={box_x}:y={box_y}:w={box_w}:h={box_h}"
            f":color={ffmpeg_bg}:t=fill"
            f":enable='{enable}'"
        )

        # Text
        text_y = y_pos
        # For multi-line: center the block
        # Using text_h expression isn't always reliable, so use fixed estimate
        text_y = box_y + pad_y

        filters.append(
            f"drawtext=text='{safe_text}'{font_arg}"
            f":fontsize={fontsize}:fontcolor={fontcolor}"
            f":borderw={border_w}:bordercolor={border_color}"
            f":x=(w-text_w)/2"
            f":y={text_y}"
            f":line_spacing=6"
            f":enable='{enable}'"
        )

    if not filters:
        return "null"

    return ",".join(filters)


def _hex_to_ffmpeg_color(color: str, opacity: float) -> str:
    """
    Convert color + opacity to FFmpeg color@opacity format.
    FFmpeg accepts: black@0.7, white@0.5, 0x000000@0.7
    """
    if color.startswith("#"):
        # Convert #RRGGBB to 0xRRGGBB
        hex_val = "0x" + color[1:]
        return f"{hex_val}@{opacity:.2f}"
    return f"{color}@{opacity:.2f}"


# ── LEGACY CAPTION FUNCTIONS (retained for voice_line captions) ────────────────

def _estimate_timings(text: str, words_per_second: float = 2.8) -> list[dict]:
    """
    Fallback: estimate word timings from text alone.
    Used when TTS boundary events fail.
    """
    words = [w for w in text.upper().split() if w]
    timings, t = [], 0.5
    for word in words:
        duration = max(0.2, len(word) * 0.055)
        timings.append({"word": word, "start": round(t, 3), "end": round(t + duration, 3)})
        t += duration + 0.05
    return timings


def group_into_chunks(timings: list[dict], chunk_size: int = 1) -> list[dict]:
    """Group word timings into display chunks."""
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
    Legacy word-by-word caption builder for voice_line display.
    Used as a supplement to scenario overlays (shows animal's inner voice words).
    Positioned at BOTTOM of screen so it doesn't conflict with scenario overlays.
    """
    if not chunks:
        return "null"

    font_arg = f":fontfile='{font_path.replace(chr(92), '/')}'" if font_path else ""
    filters  = []

    for idx, chunk in enumerate(chunks):
        safe = _sanitize_text(chunk["text"])
        if not safe:
            continue

        t_start = chunk["start"]
        t_end   = chunk["end"] + 0.08

        # Voice captions at bottom — italic-style smaller font
        is_highlight = len(safe) > 5 or idx % 3 == 0
        font_color   = "#AAFFAA" if is_highlight else "#DDDDDD"  # Soft green/grey
        font_size    = "52" if is_highlight else "46"

        # Bottom position — below scenario overlays
        bottom_y = int(video_h * 0.88)

        filters.append(
            f"drawtext=text='({safe})'{font_arg}"
            f":fontsize={font_size}:fontcolor={font_color}"
            f":borderw=4:bordercolor=black"
            f":x=(w-text_w)/2:y={bottom_y}"
            f":enable='between(t,{t_start:.3f},{t_end:.3f})'"
        )

    return ",".join(filters) if filters else "null"
