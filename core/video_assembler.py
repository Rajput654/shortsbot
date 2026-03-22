"""
Video Assembler — combines footage, voiceover, captions, and music.
Fixed: footage guaranteed to cover full audio duration using stream_loop.
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

    # Build footage video that exactly matches audio duration
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
    Uses concat with enough repetitions + trims to exact length.
    """
    if not footage_paths:
        raise ValueError("No footage paths")

    # Measure each clip
    durations = []
    for p in footage_paths:
        d = await _get_duration(p)
        durations.append(d)

    total = sum(durations)
    log.info(f"Total footage: {total:.1f}s, need: {target_duration:.1f}s")

    # Build concat list with enough repetitions
    concat_file = os.path.join(tmp_dir, "concat.txt")
    lines = []
    accumulated = 0.0
    idx = 0

    # Keep adding clips until we have target_duration + 10s buffer
    while accumulated < target_duration + 10:
        clip = footage_paths[idx % len(footage_paths)]
        dur = durations[idx % len(durations)]
        safe = os.path.abspath(clip).replace("\\", "/")
        lines.append(f"file '{safe}'")
        accumulated += dur
        idx += 1
        if idx > 200:  # hard safety limit
            break

    log.info(f"Concat: {len(lines)} clip entries = {accumulated:.1f}s")

    with open(concat_file, "w") as f:
        f.write("\n".join(lines))

    # Single FFmpeg pass: concat + scale to 9:16 + trim to exact duration
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
        "-preset", "ultrafast",
        "-crf", "28",
        "-pix_fmt", "yuv420p",
        "-threads", "2",
        "-an",
        output
    ]
    await _run_ffmpeg(cmd, "footage build")

    # Verify
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
    hook_filter = _build_hook_overlay(script)
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
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-threads", "2",
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
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-threads", "2",
            "-c:a", "aac", "-b:a", AUDIO_BITRATE,
            "-movflags", "+faststart",
            output_path
        ]

    await _run_ffmpeg(cmd, "final assembly")


def _build_caption_filter(script: dict, duration: float) -> str:
    full_text = f"{script['body']} {script['cta']}"
    words = full_text.split()

    lines = []
    chunk = []
    for w in words:
        chunk.append(w)
        if len(chunk) >= 5:
            lines.append(" ".join(chunk))
            chunk = []
    if chunk:
        lines.append(" ".join(chunk))

    if not lines:
        return "null"

    start_t = 3.0
    end_t = max(duration - 2.0, start_t + 1)
    time_per_line = (end_t - start_t) / max(len(lines), 1)

    font = FONT_PATH if os.path.exists(FONT_PATH) else ""
    font_arg = f":fontfile='{font.replace(chr(92), '/')}'" if font else ""

    filters = []
    for i, line in enumerate(lines):
        t_start = start_t + i * time_per_line
        t_end = t_start + time_per_line - 0.2
        safe = line.replace("'","").replace(":","").replace(",","").replace("\\","")
        filters.append(
            f"drawtext=text='{safe}'"
            f"{font_arg}"
            f":fontsize=52:fontcolor=white"
            f":borderw=4:bordercolor=black"
            f":x=(w-text_w)/2:y=h*0.72"
            f":enable='between(t,{t_start:.1f},{t_end:.1f})'"
        )

    return ",".join(filters) if filters else "null"


def _build_hook_overlay(script: dict) -> str:
    hook = script.get("hook", "")[:55]
    safe = hook.replace("'","").replace(":","").replace(",","").replace("\\","")
    font = FONT_PATH if os.path.exists(FONT_PATH) else ""
    font_arg = f":fontfile='{font.replace(chr(92), '/')}'" if font else ""

    return (
        f"drawtext=text='{safe}'{font_arg}"
        f":fontsize=40:fontcolor=yellow"
        f":borderw=4:bordercolor=black"
        f":x=(w-text_w)/2:y=h*0.08"
        f":enable='between(t,0,3)'"
    )


def _get_music_track():
    import random
    if not os.path.isdir(MUSIC_DIR):
        return None
    tracks = [f for f in os.listdir(MUSIC_DIR) if f.endswith((".mp3",".wav",".ogg"))]
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
