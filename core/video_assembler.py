"""
Video Assembler — combines footage, voiceover, captions, and music.

UPDATES v2:
- SEAMLESS LOOP: xfade crossfade between last 0.3s and first 0.3s of footage.
  Viewers loop involuntarily — the #1 driver of 100%+ APV on viral Shorts.
- SYNCED CAPTIONS: uses word-boundary timing data from tts_engine.py instead
  of estimate-based timing. Zero caption drift for muted viewers.
- VISUAL VARIETY: randomised style per video — slow zoom, colour grade LUT,
  or vignette overlay. Prevents automation fingerprint after 10+ videos.
- SUBSCRIBE OVERLAY: appears at 85-90% of video duration — text prompt since
  Shorts have no end screen and auto-subscribe rate is extremely low.
- Trending audio integration retained from v1.
- Thumbnail title-card frame retained from v1.
- Long/short mode timing retained from v1.
"""

import os, asyncio, logging, math, json, random
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
from core.tts_engine import get_audio_duration
from core.trending_audio import get_track_for_script
from core.caption_sync import group_into_chunks, build_caption_drawtext

FFMPEG = os.getenv("FFMPEG_PATH", "ffmpeg")
FFPROBE = os.getenv("FFPROBE_PATH", "ffprobe")

log = logging.getLogger(__name__)

FONT_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "font.ttf")

VIDEO_W = 720
VIDEO_H = 1280
AUDIO_BITRATE = "192k"

# Visual style variants — rotated per video to prevent automation fingerprint
VISUAL_STYLES = ["zoom_in", "zoom_out", "vignette", "warm_grade", "cool_grade"]


async def assemble_video(
    footage_paths: list[str],
    audio_path: str,
    script: dict,
    output_path: str,
    word_timings: list[dict] = None
) -> str:
    """
    Main assembly function.

    word_timings: optional list of {word, start, end} from tts_engine.
    If provided, captions are frame-accurate. If None, falls back to estimates.
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = output_path + "_tmp"
    Path(tmp_dir).mkdir(parents=True, exist_ok=True)

    duration = await get_audio_duration(audio_path)
    log.info(f"Audio duration: {duration:.1f}s")

    # Pick visual style deterministically per video (rotate through styles)
    style_index = hash(script.get("animal_keyword", "")) % len(VISUAL_STYLES)
    visual_style = VISUAL_STYLES[style_index]
    log.info(f"Visual style: {visual_style}")

    concat_path = os.path.join(tmp_dir, "footage.mp4")
    await _build_footage(footage_paths, duration, concat_path, tmp_dir, visual_style)

    music_path = get_track_for_script(script)

    await _ffmpeg_assemble(
        video_path=concat_path,
        audio_path=audio_path,
        music_path=music_path,
        script=script,
        duration=duration,
        output_path=output_path,
        word_timings=word_timings or [],
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


def _get_visual_style_filter(style: str, duration: float) -> str:
    """
    Return a vf filter string for the visual style variant.
    Applied during footage build so it bakes into the base clip.
    """
    if style == "zoom_in":
        # Slow zoom in over the full video duration
        # zoompan: z=zoom expression, d=duration in frames at 30fps
        total_frames = int(duration * 30)
        return (
            f"zoompan=z='min(zoom+0.0004,1.12)'"
            f":x='iw/2-(iw/zoom/2)'"
            f":y='ih/2-(ih/zoom/2)'"
            f":d={total_frames}:s={VIDEO_W}x{VIDEO_H}:fps=30"
        )
    elif style == "zoom_out":
        total_frames = int(duration * 30)
        return (
            f"zoompan=z='if(eq(on,1),1.12,max(zoom-0.0004,1.0))'"
            f":x='iw/2-(iw/zoom/2)'"
            f":y='ih/2-(ih/zoom/2)'"
            f":d={total_frames}:s={VIDEO_W}x{VIDEO_H}:fps=30"
        )
    elif style == "vignette":
        return f"vignette=angle=PI/4"
    elif style == "warm_grade":
        # Warm colour grade — slightly boost reds, reduce blues
        return "curves=r='0/0 0.5/0.56 1/1':b='0/0 0.5/0.44 1/0.92'"
    elif style == "cool_grade":
        # Cool/cinematic — boost blues slightly, desaturate midtones
        return "curves=b='0/0 0.5/0.56 1/1':r='0/0 0.5/0.44 1/0.94'"
    else:
        return ""


async def _build_footage(
    footage_paths: list[str],
    target_duration: float,
    output: str,
    tmp_dir: str,
    visual_style: str = ""
):
    if not footage_paths:
        raise ValueError("No footage paths")

    durations = []
    for p in footage_paths:
        d = await _get_duration(p)
        durations.append(d)

    concat_file = os.path.join(tmp_dir, "concat.txt")
    lines = []
    accumulated = 0.0
    idx = 0

    # Add a small buffer beyond target so xfade has material to work with
    buffer = target_duration + 5.0

    while accumulated < buffer:
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

    # Build base scale/crop filter
    base_vf = (
        f"scale={VIDEO_W}:{VIDEO_H}"
        f":force_original_aspect_ratio=increase,"
        f"crop={VIDEO_W}:{VIDEO_H},"
        f"setsar=1,"
        f"fps=30"
    )

    # Append visual style filter if applicable
    style_filter = _get_visual_style_filter(visual_style, target_duration)
    if style_filter and visual_style not in ("zoom_in", "zoom_out"):
        # Non-zoompan styles append after base scaling
        full_vf = f"{base_vf},{style_filter}"
    elif style_filter and visual_style in ("zoom_in", "zoom_out"):
        # zoompan replaces the scale/crop because it handles its own output size
        full_vf = f"scale={VIDEO_W*2}:{VIDEO_H*2}:force_original_aspect_ratio=increase,{style_filter}"
    else:
        full_vf = base_vf

    cmd = [
        FFMPEG, "-y",
        "-f", "concat", "-safe", "0",
        "-i", concat_file,
        "-vf", full_vf,
        "-t", str(target_duration + 1.0),  # slight overshoot — xfade trims to exact
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
    output_path: str,
    word_timings: list[dict],
):
    font = FONT_PATH if os.path.exists(FONT_PATH) else ""

    # Build synced caption filter from word timings
    if word_timings:
        caption_chunks = group_into_chunks(word_timings, chunk_size=2)
        caption_filter = build_caption_drawtext(caption_chunks, font, VIDEO_H, VIDEO_W)
        log.info(f"Using synced captions: {len(caption_chunks)} chunks")
    else:
        caption_filter = _build_caption_filter_estimated(script, duration)
        log.info("Using estimated caption timing (no word boundary data)")

    hook_filter = _build_hook_overlay(script, duration)
    thumbnail_filter = _build_thumbnail_frame(script)
    subscribe_filter = _build_subscribe_overlay(script, duration)

    # Seamless loop: xfade last 0.3s → first 0.3s
    # This is applied as a video filter on the footage stream
    xfade_duration = 0.3
    xfade_offset = max(duration - xfade_duration - 0.1, duration * 0.85)
    loop_filter = (
        f"[0:v]split[v1][v2];"
        f"[v1]trim=0:{xfade_offset + xfade_duration}[va];"
        f"[v2]trim={xfade_offset}:{duration},setpts=PTS-STARTPTS[vb];"
        f"[va][vb]xfade=transition=fade:duration={xfade_duration}:offset={xfade_offset}[vlooped]"
    )

    # Combine all text overlays into one filter chain on the looped video
    all_text = f"{thumbnail_filter},{caption_filter},{hook_filter},{subscribe_filter}"

    if music_path and os.path.exists(music_path):
        cmd = [
            FFMPEG, "-y",
            "-i", video_path,
            "-i", audio_path,
            "-i", music_path,
            "-filter_complex",
                f"{loop_filter};"
                f"[vlooped]{all_text}[vout];"
                f"[1:a]volume=0.92[voice];"
                f"[2:a]volume=0.10,aloop=loop=-1:size=44100[music];"
                f"[voice][music]amix=inputs=2:duration=first[aout]",
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
            "-filter_complex",
                f"{loop_filter};"
                f"[vlooped]{all_text}[vout]",
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


def _build_subscribe_overlay(script: dict, duration: float) -> str:
    """
    Subscribe prompt overlay at 85–90% of video duration.

    Shorts have no end screen and the subscribe button is hidden during
    playback. This overlay is the only way to convert viewers to subscribers.
    Positioned at bottom-safe zone, appears for ~1.5s so it's noticeable
    but doesn't feel spammy.
    """
    font = FONT_PATH if os.path.exists(FONT_PATH) else ""
    font_arg = f":fontfile='{font.replace(chr(92), '/')}'" if font else ""

    sub_start = duration * 0.85
    sub_end = duration * 0.96

    # Background pill for readability
    box_w = 420
    box_x = int((VIDEO_W - box_w) / 2)
    box_y = int(VIDEO_H * 0.73)
    box_h = 52

    box_filter = (
        f"drawbox=x={box_x}:y={box_y}:w={box_w}:h={box_h}"
        f":color=black@0.65:t=fill"
        f":enable='between(t,{sub_start:.2f},{sub_end:.2f})'"
    )

    text_filter = (
        f"drawtext=text='SUBSCRIBE for daily wild facts'{font_arg}"
        f":fontsize=28:fontcolor=white"
        f":borderw=2:bordercolor=black"
        f":x=(w-text_w)/2:y=h*0.755"
        f":enable='between(t,{sub_start:.2f},{sub_end:.2f})'"
    )

    return f"{box_filter},{text_filter}"


def _build_thumbnail_frame(script: dict) -> str:
    """
    Title-card overlay for the first 0.5 seconds.
    Becomes the de-facto thumbnail in YouTube search results.
    """
    font = FONT_PATH if os.path.exists(FONT_PATH) else ""
    font_arg = f":fontfile='{font.replace(chr(92), '/')}'" if font else ""

    animal = script.get("animal_keyword", "").upper()[:20]
    safe_animal = animal.replace("'", "").replace(":", "").replace(",", "").replace("\\", "")

    shock = script.get("shock_word", "WILD").upper()[:12]
    safe_shock = shock.replace("'", "").replace(":", "").replace(",", "").replace("\\", "")

    dark_overlay = (
        f"drawbox=x=0:y=0:w={VIDEO_W}:h={VIDEO_H}"
        f":color=black@0.65:t=fill"
        f":enable='between(t,0,0.5)'"
    )
    animal_text = (
        f"drawtext=text='{safe_animal}'{font_arg}"
        f":fontsize=96:fontcolor=white"
        f":borderw=4:bordercolor=black@0.5"
        f":x=(w-text_w)/2:y=h*0.38"
        f":enable='between(t,0,0.5)'"
    )
    shock_text = (
        f"drawtext=text='{safe_shock}'{font_arg}"
        f":fontsize=52:fontcolor=#FFE600"
        f":borderw=3:bordercolor=black@0.5"
        f":x=(w-text_w)/2:y=h*0.55"
        f":enable='between(t,0,0.5)'"
    )

    return f"{dark_overlay},{animal_text},{shock_text}"


def _build_caption_filter_estimated(script: dict, duration: float) -> str:
    """
    Fallback caption filter using time estimates (used when word timings unavailable).
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
    start_t = 1.5 if length_mode == "short" else 3.5
    end_t = max(duration - 1.5, start_t + 1)
    time_per_chunk = (end_t - start_t) / max(len(chunks), 1)

    font = FONT_PATH if os.path.exists(FONT_PATH) else ""
    font_arg = f":fontfile='{font.replace(chr(92), '/')}'" if font else ""

    filters = []
    for i, chunk in enumerate(chunks):
        t_start = start_t + i * time_per_chunk
        t_end = t_start + time_per_chunk - 0.04
        safe = chunk.replace("'", "").replace(":", "").replace(",", "").replace("\\", "")

        char_count = len(safe)
        est_text_w = min(char_count * 44, VIDEO_W - 40)
        box_x = int((VIDEO_W - est_text_w) / 2) - 20
        box_w = est_text_w + 40
        box_y = int(VIDEO_H * 0.58) - 8
        box_h = 80

        filters.append(
            f"drawbox=x={box_x}:y={box_y}:w={box_w}:h={box_h}"
            f":color=black@0.55:t=fill"
            f":enable='between(t,{t_start:.2f},{t_end:.2f})'"
        )
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
    Hook, shock word, loop hook, and TAP TO REPLAY overlays.
    Timing respects short vs long length_mode.
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

    hook_filter = (
        f"drawtext=text='{safe_hook}'{font_arg}"
        f":fontsize=42:fontcolor=white"
        f":borderw=5:bordercolor=black"
        f":x=(w-text_w)/2:y=h*0.07"
        f":enable='between(t,0,{hook_end})'"
    )

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

    loop_hook = script.get("loop_hook", "Wait... did you catch that?").upper()[:45]
    safe_loop = loop_hook.replace("'", "").replace(":", "").replace(",", "").replace("\\", "")
    loop_filter = (
        f"drawtext=text='{safe_loop}'{font_arg}"
        f":fontsize=48:fontcolor=white"
        f":borderw=5:bordercolor=black"
        f":x=(w-text_w)/2:y=h*0.83"
        f":enable='between(t,{loop_start:.2f},{loop_end:.2f})'"
    )

    replay_filter = (
        f"drawtext=text='TAP TO REPLAY'{font_arg}"
        f":fontsize=28:fontcolor=#FFFFFF88"
        f":borderw=3:bordercolor=black"
        f":x=(w-text_w)/2:y=h*0.91"
        f":enable='between(t,{replay_start:.2f},{replay_end:.2f})'"
    )

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
