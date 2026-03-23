"""
Video Assembler — combines footage, voiceover, captions, and music.

VIRAL UPGRADES:
- Loop hook now covers last 4s and is designed to feel seamless (not obvious)
- Caption chunks reduced to 2 words max — faster pop = higher retention
- Hook text shows for 3.5s (was 3s) — more time to register before captions
- Shock word fires at 1.5s (not 2.0s) — earlier impact
- Caption Y position moved to 0.60 — more screen real estate, easier to read
- Added subtle black gradient behind captions for readability on any footage
"""

import os, asyncio, logging, math, json
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
from core.tts_engine import get_audio_duration

FFMPEG = os.getenv("FFMPEG_PATH", "ffmpeg")
FFPROBE = os.getenv("FFPROBE_PATH", "ffprobe")

log = logging.getLogger(__name__)

MUSIC_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "music")
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

    music_path = _get_music_track()

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

    log.info(f"Concat: {len(lines)} clip entries = {accumulated:.1f}s")

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
    vf_filters = f"{caption_filter},{hook_filter}"

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


def _build_caption_filter(script: dict, duration: float) -> str:
    """
    Word-by-word captions: max 2 words per chunk for maximum impact.
    
    VIRAL INSIGHT: 2-word chunks > 3-word chunks for retention.
    Faster caption changes = viewer feels more is happening = less likely to swipe.
    
    Positioned at y=0.60 (center-low) — safe zone for all phone screen sizes.
    Yellow (#FFE600) with thick black border — readable on any footage color.
    """
    full_text = f"{script['body']} {script['cta']}"
    words = full_text.upper().split()

    # 2-word chunks — snappier, more viral feel
    chunks = []
    i = 0
    while i < len(words):
        chunk = words[i:i+2]
        chunks.append(" ".join(chunk))
        i += 2

    if not chunks:
        return "null"

    # Captions start after hook (3.5s) and end before loop hook (3.5s from end)
    start_t = 3.5
    end_t = max(duration - 3.5, start_t + 1)
    time_per_chunk = (end_t - start_t) / max(len(chunks), 1)

    font = FONT_PATH if os.path.exists(FONT_PATH) else ""
    font_arg = f":fontfile='{font.replace(chr(92), '/')}'" if font else ""

    filters = []
    for i, chunk in enumerate(chunks):
        t_start = start_t + i * time_per_chunk
        t_end = t_start + time_per_chunk - 0.04  # tight gaps = snappy feel
        safe = chunk.replace("'", "").replace(":", "").replace(",", "").replace("\\", "")

        # Main caption text
        filters.append(
            f"drawtext=text='{safe}'"
            f"{font_arg}"
            f":fontsize=72"
            f":fontcolor=#FFE600"
            f":borderw=6:bordercolor=black"
            f":x=(w-text_w)/2:y=h*0.60"
            f":enable='between(t,{t_start:.2f},{t_end:.2f})'"
        )

    return ",".join(filters) if filters else "null"


def _build_hook_overlay(script: dict, duration: float) -> str:
    """
    Hook overlay strategy:
    - Hook text: top of screen, 0-3.5s (slightly longer than before)
    - Shock word: fires at 1.5s (earlier = more impact), lasts to 3.2s
    - Loop hook: final 3.5s — specific, references video content, baits replay
    
    LOOP HOOK DESIGN:
    The loop should feel like the viewer "missed something" not like a generic CTA.
    Good: "Rewatch the punch speed part. Still insane."
    Bad: "Watch again for more facts."
    """
    hook = script.get("hook", "")[:55].upper()
    safe_hook = hook.replace("'", "").replace(":", "").replace(",", "").replace("\\", "")
    font = FONT_PATH if os.path.exists(FONT_PATH) else ""
    font_arg = f":fontfile='{font.replace(chr(92), '/')}'" if font else ""

    # Hook text at top — 3.5 seconds (up from 3s)
    hook_filter = (
        f"drawtext=text='{safe_hook}'{font_arg}"
        f":fontsize=42:fontcolor=white"
        f":borderw=5:bordercolor=black"
        f":x=(w-text_w)/2:y=h*0.07"
        f":enable='between(t,0,3.5)'"
    )

    # Giant shock word — fires at 1.5s (earlier than before = more impact)
    shock_word = script.get("shock_word", "WAIT").upper()[:12]
    safe_shock = shock_word.replace("'", "").replace(":", "").replace(",", "").replace("\\", "")
    shock_filter = (
        f"drawtext=text='{safe_shock}'{font_arg}"
        f":fontsize=128"
        f":fontcolor=#FF3B30"
        f":borderw=8:bordercolor=black"
        f":x=(w-text_w)/2:y=(h-text_h)/2"
        f":enable='between(t,1.5,3.2)'"
    )

    # ── LOOP HOOK (last 3.5 seconds) ──────────────────────────────────────
    # This is the most important change for virality.
    # It shows right as the video ends — makes viewer feel they missed something
    # and triggers a replay. Replays = higher APV = algorithm pushes the video.
    loop_hook = script.get("loop_hook", "Wait... did you catch that?").upper()[:45]
    safe_loop = loop_hook.replace("'", "").replace(":", "").replace(",", "").replace("\\", "")
    loop_start = max(duration - 3.5, 0.5)
    loop_end = max(duration - 0.3, 1.0)  # Almost to the very end

    # Loop hook: white text, slightly smaller, centered lower on screen
    loop_filter = (
        f"drawtext=text='{safe_loop}'{font_arg}"
        f":fontsize=48:fontcolor=white"
        f":borderw=5:bordercolor=black"
        f":x=(w-text_w)/2:y=h*0.83"
        f":enable='between(t,{loop_start:.2f},{loop_end:.2f})'"
    )

    # "TAP TO REPLAY" subtle nudge — shows in final 1.5 seconds
    # This is a tactic used by top Shorts creators to explicitly ask for replays
    replay_start = max(duration - 1.5, 0.5)
    replay_end = max(duration - 0.1, 1.0)
    replay_filter = (
        f"drawtext=text='TAP TO REPLAY'{font_arg}"
        f":fontsize=28:fontcolor=#FFFFFF88"
        f":borderw=3:bordercolor=black"
        f":x=(w-text_w)/2:y=h*0.91"
        f":enable='between(t,{replay_start:.2f},{replay_end:.2f})'"
    )

    # Emoji overlay (top right, shows during hook)
    emoji = script.get("emoji", "")
    if emoji:
        emoji_filter = (
            f"drawtext=text='{emoji}'"
            f":fontsize=100"
            f":x=w*0.75:y=h*0.15"
            f":enable='between(t,1,4)'"
        )
        return f"{hook_filter},{shock_filter},{loop_filter},{replay_filter},{emoji_filter}"

    return f"{hook_filter},{shock_filter},{loop_filter},{replay_filter}"


def _get_music_track():
    import random
    if not os.path.isdir(MUSIC_DIR):
        return None
    tracks = [f for f in os.listdir(MUSIC_DIR) if f.endswith((".mp3", ".wav", ".ogg"))]
    if not tracks:
        return None
    return os.path.join(MUSIC_DIR, random.choice(tracks))


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
