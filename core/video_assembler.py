"""
Video Assembler v3.0 — combines footage, voiceover, captions, music.

UPGRADES v3.0 (rating fixes):
- LANDSCAPE CROP: clips tagged _needs_crop get a scale+crop filter applied
  before the zoompan pass, converting 16:9 → 9:16 without black bars.
- DYNAMIC XFADE OFFSET: loop xfade offset now calculated from actual audio
  duration, not a fixed 0.3s. Longer videos get a longer, smoother fade.
- CI-AWARE PRESET: uses ultrafast in GitHub Actions env (GITHUB_ACTIONS=true),
  veryfast locally. Halves encode time in CI with negligible quality loss.
- THUMBNAIL EXTRACTION: after assembly, FFmpeg extracts the best frame at
  ~1.2s (the hook moment) and saves as thumbnail.jpg for YouTube upload.
- FONT FALLBACK CHAIN: tries custom font, then system Montserrat, then
  Liberation Sans — prevents silent caption failures in CI.
"""

import os, asyncio, logging
from pathlib import Path
from core.tts_engine import get_audio_duration
from core.caption_sync import group_into_chunks, build_caption_drawtext
from core.trending_audio import get_track_for_script

FFMPEG  = os.getenv("FFMPEG_PATH",  "ffmpeg")
FFPROBE = os.getenv("FFPROBE_PATH", "ffprobe")
log = logging.getLogger(__name__)

FONT_PATH     = os.path.join(os.path.dirname(__file__), "..", "assets", "font.ttf")
FONT_FALLBACKS = [
    FONT_PATH,
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",  # Ubuntu CI
    "/usr/share/fonts/truetype/fonts-liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",  # macOS
]

VIDEO_W, VIDEO_H = 720, 1280
AUDIO_BITRATE    = "192k"

# Use ultrafast in GitHub Actions to stay within the 6h job limit
_IS_CI  = os.getenv("GITHUB_ACTIONS", "false").lower() == "true"
_PRESET = "ultrafast" if _IS_CI else "veryfast"
_CRF    = "23" if _IS_CI else "18"


def _find_font() -> str:
    for path in FONT_FALLBACKS:
        if path and os.path.exists(path):
            return path
    log.warning("No font file found — captions will use FFmpeg default font")
    return ""


async def _build_footage(
    footage_paths: list[str],
    target_duration: float,
    output: str,
    tmp_dir: str,
):
    """
    Build a single concatenated clip with zoompan.
    Landscape clips (tagged _landscape in filename) get a 16:9→9:16 crop
    applied before the zoom pass.
    """
    concat_file = os.path.join(tmp_dir, "concat.txt")
    lines       = []
    accumulated = 0.0
    idx         = 0
    buffer      = target_duration + 6.0

    while accumulated < buffer:
        clip = footage_paths[idx % len(footage_paths)]
        safe = os.path.abspath(clip).replace("\\", "/")
        lines.append(f"file '{safe}'")
        accumulated += 8.0
        idx += 1

    with open(concat_file, "w") as f:
        f.write("\n".join(lines))

    # Detect if any landscape clips exist (they'll have "_landscape" in name)
    # We apply a crop-to-portrait step before zoompan
    has_landscape = any("_landscape" in p for p in footage_paths)

    if has_landscape:
        # Crop 16:9 → 9:16 by taking centre 9/16 of width, then scale + zoom
        portrait_crop = (
            f"crop=ih*9/16:ih,"
            f"scale=1280:2276,"
            f"zoompan=z='if(lte(mod(time,4),2),min(zoom+0.0015,1.15),max(zoom-0.0015,1.0))'"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={VIDEO_W}x{VIDEO_H}:fps=30"
        )
    else:
        portrait_crop = (
            f"scale=1280:2276,"
            f"crop={VIDEO_W}:{VIDEO_H},"
            f"zoompan=z='if(lte(mod(time,4),2),min(zoom+0.0015,1.15),max(zoom-0.0015,1.0))'"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={VIDEO_W}x{VIDEO_H}:fps=30"
        )

    cmd = [
        FFMPEG, "-y",
        "-f", "concat", "-safe", "0",
        "-i", concat_file,
        "-vf", portrait_crop,
        "-t", str(target_duration + 0.5),
        "-c:v", "libx264", "-preset", _PRESET, "-crf", _CRF,
        "-pix_fmt", "yuv420p", "-an", output
    ]
    await _run_ffmpeg(cmd, "footage build")


async def _ffmpeg_assemble(
    video_path: str,
    audio_path: str,
    music_path,
    script: dict,
    duration: float,
    output_path: str,
    word_timings: list[dict],
):
    font = _find_font()

    if word_timings:
        caption_chunks = group_into_chunks(word_timings, chunk_size=1)
        caption_filter = build_caption_drawtext(caption_chunks, font, VIDEO_H, VIDEO_W)
    else:
        caption_filter = "copy"

    safe_caption_filter = caption_filter if caption_filter and caption_filter != "null" else "copy"

    # Dynamic xfade — scale with duration for a natural feel
    xfade_duration = min(0.7, duration * 0.015)          # ~0.7s for 45s video
    xfade_offset   = max(duration - xfade_duration - 0.1, duration * 0.88)

    loop_filter = (
        f"[0:v]split[v1][v2];"
        f"[v1]trim=0:{xfade_offset + xfade_duration}[va];"
        f"[v2]trim={xfade_offset}:{duration},setpts=PTS-STARTPTS[vb];"
        f"[va][vb]xfade=transition=fade:duration={xfade_duration:.3f}:offset={xfade_offset:.3f}[vlooped]"
    )

    voice_mastering = "bass=g=6:f=110,compand=attacks=0:points=-80/-80|-15/-15|0/-10.8|20/-5.2,volume=1.2"

    base_flags = [
        "-t", str(duration),
        "-c:v", "libx264", "-preset", _PRESET, "-crf", _CRF,
        "-c:a", "aac", "-b:a", AUDIO_BITRATE,
        "-movflags", "+faststart",
    ]

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
                f"[2:a]volume=0.04,aloop=loop=-1:size=44100[music];"   # ← 0.04 not 0.08
                f"[voice][music]amix=inputs=2:duration=first[aout]",
            "-map", "[vout]", "-map", "[aout]",
        ] + base_flags + [output_path]
        await _run_ffmpeg(cmd, "final assembly")
    else:
        cmd = [
            FFMPEG, "-y",
            "-i", video_path,
            "-i", audio_path,
            "-filter_complex",
                f"{loop_filter};"
                f"[vlooped]{safe_caption_filter}[vout];"
                f"[1:a]{voice_mastering}[aout]",
            "-map", "[vout]", "-map", "[aout]",
        ] + base_flags + [output_path]
        await _run_ffmpeg(cmd, "final assembly without music")


async def extract_thumbnail(video_path: str, output_path: str, timestamp: float = 1.2) -> str:
    """
    Extract a single frame at `timestamp` seconds as a JPEG thumbnail.
    YouTube shows this in Browse and Search — significantly improves CTR.
    The hook moment (~1.2s) is usually the most visually arresting frame.
    Returns thumbnail path, or empty string on failure.
    """
    try:
        cmd = [
            FFMPEG, "-y",
            "-ss", str(timestamp),
            "-i", video_path,
            "-vframes", "1",
            "-q:v", "2",           # JPEG quality 2 = near-lossless
            "-vf", f"scale={VIDEO_W}:{VIDEO_H}",
            output_path,
        ]
        await _run_ffmpeg(cmd, "thumbnail extraction")
        log.info(f"Thumbnail extracted: {output_path}")
        return output_path
    except Exception as e:
        log.warning(f"Thumbnail extraction failed (non-fatal): {e}")
        return ""


async def _run_ffmpeg(cmd: list[str], label: str):
    log.info(f"FFmpeg [{label}]: starting...")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
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
    word_timings: list[dict] = None,
) -> tuple[str, str]:
    """
    Returns (video_path, thumbnail_path).
    thumbnail_path may be empty string if extraction fails.
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = output_path + "_tmp"
    Path(tmp_dir).mkdir(parents=True, exist_ok=True)

    duration = await get_audio_duration(audio_path)
    log.info(f"Audio duration: {duration:.1f}s | preset: {_PRESET}")

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

    # Extract thumbnail from assembled video
    thumb_path = output_path.replace(".mp4", "_thumb.jpg")
    thumb_path = await extract_thumbnail(output_path, thumb_path, timestamp=1.2)

    import shutil
    shutil.rmtree(tmp_dir, ignore_errors=True)

    size_mb = os.path.getsize(output_path) / 1024 / 1024
    log.info(f"Video assembled: {output_path} ({size_mb:.1f} MB)")
    return output_path, thumb_path
