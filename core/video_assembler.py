"""
Video Assembler — combines footage, voiceover, captions, and music.

VIRAL UPDATES & CRASH FIXES: 
- Podcast Audio Mastering: Bass boost + Compression for 'Authority' voice.
- Dynamic Punch-in Cuts: Automated camera movement every 4 seconds.
- Frame-Accurate Sync: 1-word rapid-fire captions.
- SAFETY: Prevents FFmpeg 'null filter' crashes and handles missing fonts.
"""
import os, asyncio, logging, json, random
from pathlib import Path
from core.tts_engine import get_audio_duration
from core.caption_sync import group_into_chunks, build_caption_drawtext
from core.trending_audio import get_track_for_script

FFMPEG = os.getenv("FFMPEG_PATH", "ffmpeg")
FFPROBE = os.getenv("FFPROBE_PATH", "ffprobe")
log = logging.getLogger(__name__)

FONT_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "font.ttf")
VIDEO_W, VIDEO_H = 720, 1280
AUDIO_BITRATE = "192k"

async def _build_footage(
    footage_paths: list[str],
    target_duration: float,
    output: str,
    tmp_dir: str
):
    """Alternating Punch-In / Punch-Out cuts. Resets zoom every 4 seconds."""
    concat_file = os.path.join(tmp_dir, "concat.txt")
    lines = []
    accumulated = 0.0
    idx = 0
    buffer = target_duration + 5.0

    while accumulated < buffer:
        clip = footage_paths[idx % len(footage_paths)]
        safe = os.path.abspath(clip).replace("\\", "/")
        lines.append(f"file '{safe}'")
        accumulated += 8.0 # Estimate per Pexels clip
        idx += 1

    with open(concat_file, "w") as f:
        f.write("\n".join(lines))

    # Overscale to 1280p to prevent pixelation during zoom
    dynamic_cut_filter = (
        f"scale=1280:2276,crop=720:1280," 
        f"zoompan=z='if(lte(mod(time,4),2), min(zoom+0.0015,1.15), max(zoom-0.0015,1.0))'"
        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={VIDEO_W}x{VIDEO_H}:fps=30"
    )

    cmd = [
        FFMPEG, "-y",
        "-f", "concat", "-safe", "0",
        "-i", concat_file,
        "-vf", dynamic_cut_filter,
        "-t", str(target_duration + 0.5),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", 
        "-pix_fmt", "yuv420p", "-an", output
    ]
    await _run_ffmpeg(cmd, "footage build")

async def _ffmpeg_assemble(
    video_path: str, audio_path: str, music_path, script: dict,
    duration: float, output_path: str, word_timings: list[dict],
):
    # ERROR FIX 1: Font Fallback safety for headless servers
    if os.path.exists(FONT_PATH):
        font = FONT_PATH
    else:
        log.warning(f"Custom font not found at {FONT_PATH}. Using system default.")
        font = "" 

    # Viral Retention: 1-word rapid fire captions
    if word_timings:
        caption_chunks = group_into_chunks(word_timings, chunk_size=1)
        caption_filter = build_caption_drawtext(caption_chunks, font, VIDEO_H, VIDEO_W)
    else:
        caption_filter = "null"

    # ERROR FIX 2: Prevent FFmpeg "null filter" crash if timings fail
    safe_caption_filter = caption_filter if caption_filter != "null" else "copy"

    # Seamless Loop: Involuntary rewatch trigger
    xfade_duration = 0.3
    xfade_offset = max(duration - xfade_duration - 0.1, duration * 0.85)
    loop_filter = (
        f"[0:v]split[v1][v2];"
        f"[v1]trim=0:{xfade_offset + xfade_duration}[va];"
        f"[v2]trim={xfade_offset}:{duration},setpts=PTS-STARTPTS[vb];"
        f"[va][vb]xfade=transition=fade:duration={xfade_duration}:offset={xfade_offset}[vlooped]"
    )

    # Audio Mastering Chain: Deep Bass + Tight Compression
    voice_mastering = "bass=g=6:f=110,compand=attacks=0:points=-80/-80|-15/-15|0/-10.8|20/-5.2,volume=1.2"

    if music_path and os.path.exists(music_path):
        cmd = [
            FFMPEG, "-y",
            "-i", video_path,
            "-i", audio_path,
            "-i", music_path,
            "-filter_complex",
                f"{loop_filter};"
                f"[vlooped]{safe_caption_filter}[vout];"
                f"[1:a]{voice_mastering}[voice];"
                f"[2:a]volume=0.08,aloop=loop=-1:size=44100[music];"
                f"[voice][music]amix=inputs=2:duration=first[aout]",
            "-map", "[vout]", "-map", "[aout]",
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-c:a", "aac", "-b:a", AUDIO_BITRATE,
            "-movflags", "+faststart",
            output_path
        ]
        await _run_ffmpeg(cmd, "final assembly")
    else:
        # Fallback if music track is missing
        cmd = [
            FFMPEG, "-y",
            "-i", video_path,
            "-i", audio_path,
            "-filter_complex",
                f"{loop_filter};"
                f"[vlooped]{safe_caption_filter}[vout];"
                f"[1:a]{voice_mastering}[aout]",
            "-map", "[vout]", "-map", "[aout]",
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-c:a", "aac", "-b:a", AUDIO_BITRATE,
            "-movflags", "+faststart",
            output_path
        ]
        await _run_ffmpeg(cmd, "final assembly without music")

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

async def assemble_video(
    footage_paths: list[str],
    audio_path: str,
    script: dict,
    output_path: str,
    word_timings: list[dict] = None
) -> str:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = output_path + "_tmp"
    Path(tmp_dir).mkdir(parents=True, exist_ok=True)

    duration = await get_audio_duration(audio_path)
    log.info(f"Audio duration: {duration:.1f}s")

    concat_path = os.path.join(tmp_dir, "footage.mp4")
    await _build_footage(footage_paths, duration, concat_path, tmp_dir)

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
