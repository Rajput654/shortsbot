"""
Video Assembler — combines footage, voiceover, captions, and music.
Upgraded: word-by-word yellow captions, giant shock-word overlay, loop-hook at end, CRF 20 quality.
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
    """
    Build footage video that fills exactly target_duration seconds.
    """
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
                f"[1:a]volume=0.90[voice];"
                f"[2:a]volume=0.12,aloop=loop=-1:size=44100[music];"
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
    Word-by-word pop-in captions styled like MrBeast/viral Shorts.
    Yellow text, ALL CAPS, chunked into 2-3 word bursts for maximum impact.
    Positioned at y=0.65 to leave room for loop hook at bottom.
    """
    full_text = f"{script['body']} {script['cta']}"
    words = full_text.upper().split()

    # Chunk into 2-3 word bursts for viral caption style
    chunks = []
    i = 0
    while i < len(words):
        size = 2 if len(chunks) % 2 == 0 else 3
        chunk = words[i:i+size]
        chunks.append(" ".join(chunk))
        i += size

    if not chunks:
        return "null"

    start_t = 3.0
    end_t = max(duration - 4.0, start_t + 1)  # leave 4s for loop hook at end
    time_per_chunk = (end_t - start_t) / max(len(chunks), 1)

    font = FONT_PATH if os.path.exists(FONT_PATH) else ""
    font_arg = f":fontfile='{font.replace(chr(92), '/')}'" if font else ""

    filters = []
    for i, chunk in enumerate(chunks):
        t_start = start_t + i * time_per_chunk
        t_end = t_start + time_per_chunk - 0.05  # tight gaps = snappy feel
        safe = chunk.replace("'", "").replace(":", "").replace(",", "").replace("\\", "")
        filters.append(
            f"drawtext=text='{safe}'"
            f"{font_arg}"
            f":fontsize=68"
            f":fontcolor=#FFE600"
            f":borderw=5:bordercolor=black"
            f":x=(w-text_w)/2:y=h*0.65"   # moved up from 0.70 to avoid loop hook overlap
            f":enable='between(t,{t_start:.2f},{t_end:.2f})'"
        )

    return ",".join(filters) if filters else "null"


def _build_hook_overlay(script: dict, duration: float) -> str:
    """
    Hook text at top (0-3s) + giant SHOCK WORD fires at 2s (during hook, before captions).
    Loop hook at bottom in final 4 seconds to trigger replays.
    """
    hook = script.get("hook", "")[:55].upper()
    safe_hook = hook.replace("'", "").replace(":", "").replace(",", "").replace("\\", "")
    font = FONT_PATH if os.path.exists(FONT_PATH) else ""
    font_arg = f":fontfile='{font.replace(chr(92), '/')}'" if font else ""

    # Hook text at top for first 3 seconds
    hook_filter = (
        f"drawtext=text='{safe_hook}'{font_arg}"
        f":fontsize=44:fontcolor=white"
        f":borderw=5:bordercolor=black"
        f":x=(w-text_w)/2:y=h*0.07"
        f":enable='between(t,0,3)'"
    )

    # Giant red SHOCK WORD fires at 2s (DURING hook, not when captions start)
    # This prevents visual collision between shock word and captions
    shock_word = script.get("shock_word", "WAIT").upper()[:12]
    safe_shock = shock_word.replace("'", "").replace(":", "").replace(",", "").replace("\\", "")
    shock_filter = (
        f"drawtext=text='{safe_shock}'{font_arg}"
        f":fontsize=120"
        f":fontcolor=#FF3B30"
        f":borderw=8:bordercolor=black"
        f":x=(w-text_w)/2:y=(h-text_h)/2"
        f":enable='between(t,2.0,3.5)'"   # was 3.0-4.5 — now fires DURING hook before captions
    )

    # Loop hook at bottom — shows in final 4 seconds to bait replays
    loop_hook = script.get("loop_hook", "Wait... did you catch that?").upper()[:40]
    safe_loop = loop_hook.replace("'", "").replace(":", "").replace(",", "").replace("\\", "")
    loop_start = max(duration - 4.0, 0.5)
    loop_end = max(duration - 0.5, 1.0)
    loop_filter = (
        f"drawtext=text='{safe_loop}'{font_arg}"
        f":fontsize=52:fontcolor=white"
        f":borderw=5:bordercolor=black"
        f":x=(w-text_w)/2:y=h*0.82"
        f":enable='between(t,{loop_start:.2f},{loop_end:.2f})'"
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
        return f"{hook_filter},{shock_filter},{loop_filter},{emoji_filter}"

    return f"{hook_filter},{shock_filter},{loop_filter}"


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
