"""
Video Assembler — combines footage, voiceover, captions, and music.

UPDATES:
- Caption background: semi-transparent black pill behind every caption chunk.
  85% of Shorts viewers watch muted — readability is non-negotiable.
- Thumbnail title-card: first 0.5s shows a bold animal name + emoji on a dark
  overlay. This frame becomes the thumbnail in YouTube search results.
- Trending audio integration: uses core/trending_audio.py to pick energy-matched
  track instead of random selection.
- Long-mode support: video_assembler now respects script["length_mode"] to apply
  correct overlay timing for both 13s and 55-60s formats.
"""

import os, asyncio, logging, math, json
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
from core.tts_engine import get_audio_duration
from core.trending_audio import get_track_for_script

FFMPEG = os.getenv("FFMPEG_PATH", "ffmpeg")
FFPROBE = os.getenv("FFPROBE_PATH", "ffprobe")

log = logging.getLogger(__name__)

FONT_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "font.ttf")

VIDEO_W = 720
VIDEO_H = 1280
AUDIO_BITRATE = "192k"


async def assemble_video(
    footage_paths: list[str],
    audio_path: str,
    script: dict,
    output_path: str
) -> str:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = output_path + "_tmp"
    Path(tmp_dir).mkdir(parents=True, exist_ok=True)

    duration = await get_audio_duration(audio_path)
    log.info(f"Audio duration: {duration:.1f}s")

    concat_path = os.path.join(tmp_dir, "footage.mp4")
    await _build_footage(footage_paths, duration, concat_path, tmp_dir)

    # Use trending audio manager instead of random pick
    music_path = get_track_for_script(script)

    await _ffmpeg_assemble(
        video_path=concat_path,
        audio_path=audio_path,
        music_path=music_path,
        script=script,
        duration=duration,
        output_path=output_path
    )

    import shutil
    shutil.rmtree(tmp_dir, ignore_errors=True)

    size_mb = os.path.getsize(output_path) / 1024 / 1024
    log.info(f"Video assembled: {output_path} ({size_mb:.1f} MB)")
    return output_path


async def _get_duration(path: str) -> float:
    try:
        proc = await asyncio.create_subprocess_exec(
            FFPROBE, "-v", "quiet",
            "-print_format", "json",
            "-show_streams", path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        data = json.loads(stdout)
        for s in data.get("streams", []):
            if s.get("codec_type") == "video":
                return float(s.get("duration", 8))
    except Exception:
        pass
    return 8.0


async def _build_footage(
    footage_paths: list[str],
    target_duration: float,
    output: str,
    tmp_dir: str
):
    if not footage_paths:
        raise ValueError("No footage paths")

    durations = []
    for p in footage_paths:
        d = await _get_duration(p)
        durations.append(d)

    total = sum(durations)
    log.info(f"Total footage: {total:.1f}s, need: {target_duration:.1f}s")

    concat_file = os.path.join(tmp_dir, "concat.txt")
    lines = []
    accumulated = 0.0
    idx = 0

    while accumulated < target_duration + 10:
        clip = footage_paths[idx % len(footage_paths)]
        dur = durations[idx % len(durations)]
        safe = os.path.abspath(clip).replace("\\", "/")
        lines.append(f"file '{safe}'")
        accumulated += dur
        idx += 1
        if idx > 200:
            break

    with open(concat_file, "w") as f:
        f.write("\n".join(lines))

    cmd = [
        FFMPEG, "-y",
        "-f", "concat", "-safe", "0",
        "-i", concat_file,
        "-vf", (
            f"scale={VIDEO_W}:{VIDEO_H}"
            f":force_original_aspect_ratio=increase,"
            f"crop={VIDEO_W}:{VIDEO_H},"
            f"setsar=1,"
            f"fps=30"
        ),
        "-t", str(target_duration),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-threads", "4",
        "-an",
        output
    ]
    await _run_ffmpeg(cmd, "footage build")

    actual = await _get_duration(output)
    log.info(f"Footage video: {actual:.1f}s (target {target_duration:.1f}s) ✓")


async def _ffmpeg_assemble(
    video_path: str,
    audio_path: str,
    music_path,
    script: dict,
    duration: float,
    output_path: str
):
    caption_filter = _build_caption_filter(script, duration)
    hook_filter = _build_hook_overlay(script, duration)
    thumbnail_filter = _build_thumbnail_frame(script)
    vf_filters = f"{thumbnail_filter},{caption_filter},{hook_filter}"

    if music_path and os.path.exists(music_path):
        cmd = [
            FFMPEG, "-y",
            "-i", video_path,
            "-i", audio_path,
            "-i", music_path,
            "-filter_complex",
                f"[1:a]volume=0.92[voice];"
                f"[2:a]volume=0.10,aloop=loop=-1:size=44100[music];"
                f"[voice][music]amix=inputs=2:duration=first[aout];"
                f"[0:v]{vf_filters}[vout]",
            "-map", "[vout]",
            "-map", "[aout]",
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-threads", "4",
            "-c:a", "aac", "-b:a", AUDIO_BITRATE,
            "-movflags", "+faststart",
            output_path
        ]
    else:
        cmd = [
            FFMPEG, "-y",
            "-i", video_path,
            "-i", audio_path,
            "-filter_complex", f"[0:v]{vf_filters}[vout]",
            "-map", "[vout]",
            "-map", "1:a",
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-threads", "4",
            "-c:a", "aac", "-b:a", AUDIO_BITRATE,
            "-movflags", "+faststart",
            output_path
        ]

    await _run_ffmpeg(cmd, "final assembly")


def _build_thumbnail_frame(script: dict) -> str:
    """
    Title-card overlay for the first 0.5 seconds.

    This frame becomes the de-facto thumbnail in YouTube search results
    and the channel page. A visually distinct title card dramatically
    improves CTR vs. a random stock footage frame.

    Design: dark semi-transparent overlay + large animal name + emoji.
    Appears ONLY in the first 0.5 seconds so it doesn't distract from
    the actual video content.
    """
    font = FONT_PATH if os.path.exists(FONT_PATH) else ""
    font_arg = f":fontfile='{font.replace(chr(92), '/')}'" if font else ""

    animal = script.get("animal_keyword", "").upper()[:20]
    safe_animal = animal.replace("'", "").replace(":", "").replace(",", "").replace("\\", "")

    emoji = script.get("emoji", "")
    shock = script.get("shock_word", "WILD").upper()[:12]
    safe_shock = shock.replace("'", "").replace(":", "").replace(",", "").replace("\\", "")

    # Dark overlay across entire frame (only 0–0.5s)
    dark_overlay = (
        f"drawbox=x=0:y=0:w={VIDEO_W}:h={VIDEO_H}"
        f":color=black@0.65:t=fill"
        f":enable='between(t,0,0.5)'"
    )

    # Large animal name centred
    animal_text = (
        f"drawtext=text='{safe_animal}'{font_arg}"
        f":fontsize=96:fontcolor=white"
        f":borderw=4:bordercolor=black@0.5"
        f":x=(w-text_w)/2:y=h*0.38"
        f":enable='between(t,0,0.5)'"
    )

    # Shock word below animal name
    shock_text = (
        f"drawtext=text='{safe_shock}'{font_arg}"
        f":fontsize=52:fontcolor=#FFE600"
        f":borderw=3:bordercolor=black@0.5"
        f":x=(w-text_w)/2:y=h*0.55"
        f":enable='between(t,0,0.5)'"
    )

    return f"{dark_overlay},{animal_text},{shock_text}"


def _build_caption_filter(script: dict, duration: float) -> str:
    """
    Word-by-word captions with semi-transparent black background pill.

    MUTED VIEWER FIX: 85% of mobile viewers watch with sound off.
    The background pill ensures text is readable on ANY footage color —
    bright sand, white snow, yellow backgrounds — all handled.

    Uses drawbox to create the pill background BEFORE drawtext renders
    the actual caption text on top.

    2-word chunks = snappier feel, higher retention.
    Positioned at y=0.60 (centre-low) — safe zone for all phone sizes.
    """
    full_text = f"{script['body']} {script['cta']}"
    words = full_text.upper().split()

    chunks = []
    i = 0
    while i < len(words):
        chunk = words[i:i+2]
        chunks.append(" ".join(chunk))
        i += 2

    if not chunks:
        return "null"

    length_mode = script.get("length_mode", "long")

    # Timing: captions start after hook, end before loop hook
    if length_mode == "short":
        start_t = 1.5   # 13s video — hook is shorter, captions start earlier
        end_t = max(duration - 1.5, start_t + 1)
    else:
        start_t = 3.5
        end_t = max(duration - 3.5, start_t + 1)

    time_per_chunk = (end_t - start_t) / max(len(chunks), 1)

    font = FONT_PATH if os.path.exists(FONT_PATH) else ""
    font_arg = f":fontfile='{font.replace(chr(92), '/')}'" if font else ""

    # Estimate text width for background box (approx 22px per char at fontsize 72)
    filters = []
    for i, chunk in enumerate(chunks):
        t_start = start_t + i * time_per_chunk
        t_end = t_start + time_per_chunk - 0.04
        safe = chunk.replace("'", "").replace(":", "").replace(",", "").replace("\\", "")

        # Estimate box width based on character count
        char_count = len(safe)
        est_text_w = min(char_count * 44, VIDEO_W - 40)  # ~44px per char at fontsize 72
        box_x = int((VIDEO_W - est_text_w) / 2) - 20
        box_w = est_text_w + 40
        box_y = int(VIDEO_H * 0.58) - 8
        box_h = 80  # tall enough for fontsize 72

        # Background pill
        filters.append(
            f"drawbox=x={box_x}:y={box_y}:w={box_w}:h={box_h}"
            f":color=black@0.55:t=fill"
            f":enable='between(t,{t_start:.2f},{t_end:.2f})'"
        )

        # Caption text on top
        filters.append(
            f"drawtext=text='{safe}'"
            f"{font_arg}"
            f":fontsize=72"
            f":fontcolor=white"
            f":borderw=4:bordercolor=black"
            f":x=(w-text_w)/2:y=h*0.60"
            f":enable='between(t,{t_start:.2f},{t_end:.2f})'"
        )

    return ",".join(filters) if filters else "null"


def _build_hook_overlay(script: dict, duration: float) -> str:
    """
    Hook overlay strategy (respects length_mode):
    - Hook text: top of screen, 0–3.5s (0–1.5s for short mode)
    - Shock word: fires at 1.5s, lasts to 3.2s (0.5s to 1.2s for short mode)
    - Loop hook: final 3.5s (1.5s for short mode)
    - "TAP TO REPLAY" subtle nudge: final 1.5s
    """
    hook = script.get("hook", "")[:55].upper()
    safe_hook = hook.replace("'", "").replace(":", "").replace(",", "").replace("\\", "")
    font = FONT_PATH if os.path.exists(FONT_PATH) else ""
    font_arg = f":fontfile='{font.replace(chr(92), '/')}'" if font else ""

    length_mode = script.get("length_mode", "long")
    is_short = length_mode == "short"

    hook_end = 1.5 if is_short else 3.5
    shock_start = 0.5 if is_short else 1.5
    shock_end = 1.2 if is_short else 3.2
    loop_window = 1.5 if is_short else 3.5
    loop_start = max(duration - loop_window, 0.5)
    loop_end = max(duration - 0.3, 1.0)
    replay_start = max(duration - 1.5, 0.5)
    replay_end = max(duration - 0.1, 1.0)

    # Hook text
    hook_filter = (
        f"drawtext=text='{safe_hook}'{font_arg}"
        f":fontsize=42:fontcolor=white"
        f":borderw=5:bordercolor=black"
        f":x=(w-text_w)/2:y=h*0.07"
        f":enable='between(t,0,{hook_end})'"
    )

    # Shock word (only show in non-thumbnail window — after 0.5s)
    shock_word = script.get("shock_word", "WAIT").upper()[:12]
    safe_shock = shock_word.replace("'", "").replace(":", "").replace(",", "").replace("\\", "")
    shock_filter = (
        f"drawtext=text='{safe_shock}'{font_arg}"
        f":fontsize=128"
        f":fontcolor=#FF3B30"
        f":borderw=8:bordercolor=black"
        f":x=(w-text_w)/2:y=(h-text_h)/2"
        f":enable='between(t,{shock_start},{shock_end})'"
    )

    # Loop hook
    loop_hook = script.get("loop_hook", "Wait... did you catch that?").upper()[:45]
    safe_loop = loop_hook.replace("'", "").replace(":", "").replace(",", "").replace("\\", "")
    loop_filter = (
        f"drawtext=text='{safe_loop}'{font_arg}"
        f":fontsize=48:fontcolor=white"
        f":borderw=5:bordercolor=black"
        f":x=(w-text_w)/2:y=h*0.83"
        f":enable='between(t,{loop_start:.2f},{loop_end:.2f})'"
    )

    # TAP TO REPLAY nudge
    replay_filter = (
        f"drawtext=text='TAP TO REPLAY'{font_arg}"
        f":fontsize=28:fontcolor=#FFFFFF88"
        f":borderw=3:bordercolor=black"
        f":x=(w-text_w)/2:y=h*0.91"
        f":enable='between(t,{replay_start:.2f},{replay_end:.2f})'"
    )

    # Emoji overlay
    emoji = script.get("emoji", "")
    if emoji:
        emoji_filter = (
            f"drawtext=text='{emoji}'"
            f":fontsize=100"
            f":x=w*0.75:y=h*0.15"
            f":enable='between(t,1,{hook_end+0.5})'"
        )
        return f"{hook_filter},{shock_filter},{loop_filter},{replay_filter},{emoji_filter}"

    return f"{hook_filter},{shock_filter},{loop_filter},{replay_filter}"


async def _run_ffmpeg(cmd: list[str], label: str):
    log.info(f"FFmpeg [{label}]: starting...")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        log.error(f"FFmpeg [{label}] failed:\n{stderr.decode()[-2000:]}")
        raise RuntimeError(f"FFmpeg failed: {label}")
    log.info(f"FFmpeg [{label}] done ✓")
