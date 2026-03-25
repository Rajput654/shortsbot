"""
Video Assembler v4.0 — Scenario Text Overlay + Beat-Synced Editing

COMPLETE OVERHAUL v4.0:
- BEAT-SYNCED CUTS: Video clips are cut/concatenated to align with scene_beat
  timestamps, so the footage CHANGES at each story beat. This is the #1 thing
  that makes animal shorts feel professionally edited.
- SCENARIO TEXT OVERLAYS: Uses build_scenario_overlays() from caption_sync
  instead of word-by-word captions. Big story text drives the joke.
- VOICE LINE CAPTIONS: Small bottom captions for animal inner monologue
  (the short voice_line text from each beat).
- CLIP VARIETY: Different footage clips for different story beats so the
  edit feels dynamic, not looping the same clip.
- AUDIO MIX: Music louder in silent sections, ducked behind voice lines.
- TOTAL DURATION: Derived from last beat timestamp + buffer, NOT audio length.
  For silent videos (no voiceover), uses scene_beats timing directly.

RETAINED from v3.1:
- Landscape crop for Pexels landscape footage
- CI-aware FFmpeg preset
- Thumbnail extraction at hook moment
- Font fallback chain
"""

import os, asyncio, logging, math
from pathlib import Path
from core.tts_engine import get_audio_duration
from core.caption_sync import (
    build_scenario_overlays,
    build_caption_drawtext,
    group_into_chunks,
)
from core.trending_audio import get_track_for_script

FFMPEG  = os.getenv("FFMPEG_PATH",  "ffmpeg")
FFPROBE = os.getenv("FFPROBE_PATH", "ffprobe")
log = logging.getLogger(__name__)

FONT_PATH      = os.path.join(os.path.dirname(__file__), "..", "assets", "font.ttf")
FONT_FALLBACKS = [
    FONT_PATH,
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/fonts-liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]

VIDEO_W, VIDEO_H = 720, 1280
AUDIO_BITRATE    = "192k"

_IS_CI  = os.getenv("GITHUB_ACTIONS", "false").lower() == "true"
_PRESET = "ultrafast" if _IS_CI else "veryfast"
_CRF    = "23"        if _IS_CI else "18"


def _find_font() -> str:
    for path in FONT_FALLBACKS:
        if path and os.path.exists(path):
            return path
    log.warning("No font file found — captions will use FFmpeg default font")
    return ""


def _get_target_duration(script: dict, audio_duration: float) -> float:
    """
    Determine the final video duration.
    For scenario videos: max(audio_duration, last beat timestamp + 3s)
    Clamp between 15s and 58s for Shorts compliance.
    """
    beats = script.get("scene_beats", [])
    if beats:
        last_ts = max(b.get("timestamp", 0) for b in beats)
        beat_duration = last_ts + 3.5  # buffer after last beat
    else:
        beat_duration = 30.0

    duration = max(audio_duration, beat_duration)
    return max(15.0, min(duration, 58.0))


async def _build_beat_synced_footage(
    footage_paths: list[str],
    scene_beats: list[dict],
    target_duration: float,
    output: str,
    tmp_dir: str,
):
    """
    Build a footage track where clips change at beat timestamps.
    Each story beat gets a different clip → feels professionally edited.

    If beats are close together (< 2s), use sub-clips.
    Each clip is trimmed to fit its beat window.
    """
    if not footage_paths:
        raise RuntimeError("No footage paths provided")

    if not scene_beats:
        # No beats — simple concat loop
        return await _build_simple_footage(footage_paths, target_duration, output, tmp_dir)

    # Build clip segments: one per beat window
    segments = []
    for i, beat in enumerate(scene_beats):
        t_start = float(beat.get("timestamp", 0.0))
        if i + 1 < len(scene_beats):
            t_end = float(scene_beats[i + 1].get("timestamp", t_start + 3.0))
        else:
            t_end = target_duration

        seg_duration = max(t_end - t_start, 1.0)
        clip_idx = i % len(footage_paths)
        segments.append({
            "clip": footage_paths[clip_idx],
            "duration": seg_duration,
            "is_landscape": "_landscape" in footage_paths[clip_idx],
        })

    # Generate each segment as a temp file, then concat
    segment_files = []
    for idx, seg in enumerate(segments):
        seg_file = os.path.join(tmp_dir, f"seg_{idx:03d}.mp4")
        clip = seg["clip"]
        dur  = seg["duration"]

        # Get actual clip duration to avoid requesting more than available
        clip_dur = await _get_clip_duration(clip)
        # Loop the clip if it's shorter than needed
        loop_count = max(1, math.ceil(dur / max(clip_dur, 0.1)) + 1) if clip_dur > 0 else 1

        if seg["is_landscape"]:
            vf = (
                f"crop=ih*9/16:ih,"
                f"scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=disable"
            )
        else:
            vf = (
                f"scale=1280:2276,"
                f"crop={VIDEO_W}:{VIDEO_H}"
            )

        # Subtle ken burns per segment — direction alternates
        direction_x = "'iw/2-(iw/zoom/2)'" if idx % 2 == 0 else "'iw/2-(iw/zoom/2)+5'"
        zoom_expr = "'min(zoom+0.001,1.08)'" if idx % 3 != 2 else "'max(zoom-0.001,1.0)'"

        cmd = [
            FFMPEG, "-y",
            "-stream_loop", str(loop_count),
            "-i", clip,
            "-vf",
            f"{vf},"
            f"zoompan=z={zoom_expr}"
            f":x={direction_x}:y='ih/2-(ih/zoom/2)'"
            f":d=1:s={VIDEO_W}x{VIDEO_H}:fps=30",
            "-t", str(dur + 0.1),
            "-c:v", "libx264", "-preset", _PRESET, "-crf", _CRF,
            "-pix_fmt", "yuv420p", "-an",
            seg_file,
        ]
        try:
            await _run_ffmpeg(cmd, f"segment {idx}")
            segment_files.append(seg_file)
        except Exception as e:
            log.warning(f"Segment {idx} failed ({e}) — using previous segment")
            if segment_files:
                segment_files.append(segment_files[-1])  # reuse previous

    if not segment_files:
        return await _build_simple_footage(footage_paths, target_duration, output, tmp_dir)

    # Concat all segments
    concat_file = os.path.join(tmp_dir, "concat_beats.txt")
    with open(concat_file, "w") as f:
        for sf in segment_files:
            safe = os.path.abspath(sf).replace("\\", "/")
            f.write(f"file '{safe}'\n")

    cmd = [
        FFMPEG, "-y",
        "-f", "concat", "-safe", "0",
        "-i", concat_file,
        "-c:v", "libx264", "-preset", _PRESET, "-crf", _CRF,
        "-pix_fmt", "yuv420p",
        "-t", str(target_duration + 0.2),
        "-an",
        output,
    ]
    await _run_ffmpeg(cmd, "beat-synced concat")


async def _get_clip_duration(clip_path: str) -> float:
    """Get video clip duration using ffprobe."""
    try:
        proc = await asyncio.create_subprocess_exec(
            FFPROBE, "-v", "quiet",
            "-print_format", "json",
            "-show_streams", clip_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        import json
        data = json.loads(stdout)
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                return float(stream.get("duration", 5.0))
    except Exception:
        pass
    return 5.0


async def _build_simple_footage(
    footage_paths: list[str],
    target_duration: float,
    output: str,
    tmp_dir: str,
):
    """Fallback: simple concatenation without beat sync."""
    concat_file = os.path.join(tmp_dir, "concat.txt")
    accumulated = 0.0
    lines = []
    idx = 0
    buffer = target_duration + 6.0

    while accumulated < buffer:
        clip = footage_paths[idx % len(footage_paths)]
        safe = os.path.abspath(clip).replace("\\", "/")
        lines.append(f"file '{safe}'")
        accumulated += 8.0
        idx += 1

    with open(concat_file, "w") as f:
        f.write("\n".join(lines))

    has_landscape = any("_landscape" in p for p in footage_paths)
    if has_landscape:
        vf = (
            f"crop=ih*9/16:ih,"
            f"scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=disable"
        )
    else:
        vf = f"scale=1280:2276,crop={VIDEO_W}:{VIDEO_H}"

    cmd = [
        FFMPEG, "-y",
        "-f", "concat", "-safe", "0",
        "-i", concat_file,
        "-vf", vf,
        "-t", str(target_duration + 0.5),
        "-c:v", "libx264", "-preset", _PRESET, "-crf", _CRF,
        "-pix_fmt", "yuv420p", "-an", output,
    ]
    await _run_ffmpeg(cmd, "simple footage build")


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
    scene_beats = script.get("scene_beats", [])

    # Build scenario overlay filter (the big story text)
    scenario_filter = build_scenario_overlays(
        scene_beats, font, VIDEO_H, VIDEO_W, total_duration=duration
    )

    # Build voice line captions (small bottom captions for inner monologue words)
    if word_timings:
        caption_chunks = group_into_chunks(word_timings, chunk_size=1)
        voice_caption_filter = build_caption_drawtext(caption_chunks, font, VIDEO_H, VIDEO_W)
    else:
        voice_caption_filter = "null"

    # Combine scenario overlays + voice captions
    # If both are "null", use "null" passthrough
    if scenario_filter == "null" and voice_caption_filter == "null":
        combined_filter = "null"
    elif scenario_filter == "null":
        combined_filter = voice_caption_filter
    elif voice_caption_filter == "null":
        combined_filter = scenario_filter
    else:
        combined_filter = f"{scenario_filter},{voice_caption_filter}"

    # Guard invalid filter value
    if not combined_filter or combined_filter == "copy":
        combined_filter = "null"

    # Gentle fade in/out at start and end
    fade_dur = min(0.4, duration * 0.05)
    fade_filter = (
        f"fade=t=in:st=0:d={fade_dur:.2f},"
        f"fade=t=out:st={max(0, duration - fade_dur - 0.1):.2f}:d={fade_dur:.2f}"
    )

    if combined_filter == "null":
        full_video_filter = fade_filter
    else:
        full_video_filter = f"{combined_filter},{fade_filter}"

    voice_mastering = (
        "bass=g=4:f=120,"
        "compand=attacks=0:points=-80/-80|-15/-15|0/-10.8|20/-5.2,"
        "volume=1.3"
    )

    base_flags = [
        "-t", str(duration),
        "-c:v", "libx264", "-preset", _PRESET, "-crf", _CRF,
        "-c:a", "aac", "-b:a", AUDIO_BITRATE,
        "-movflags", "+faststart",
    ]

    # Check if audio is silent (voice_narration is empty)
    has_voice = bool(script.get("voice_narration", "").strip())

    if music_path and os.path.exists(music_path):
        if has_voice:
            # Voice + music: duck music under voice
            cmd = [
                FFMPEG, "-y",
                "-i", video_path,
                "-i", audio_path,
                "-i", music_path,
                "-filter_complex",
                    f"[0:v]{full_video_filter}[vout];"
                    f"[1:a]{voice_mastering}[voice];"
                    f"[2:a]volume=0.06,aloop=loop=-1:size=44100[music];"
                    f"[voice][music]amix=inputs=2:duration=first[aout]",
                "-map", "[vout]", "-map", "[aout]",
            ] + base_flags + [output_path]
        else:
            # Silent video — music only, slightly louder
            cmd = [
                FFMPEG, "-y",
                "-i", video_path,
                "-i", music_path,
                "-filter_complex",
                    f"[0:v]{full_video_filter}[vout];"
                    f"[1:a]volume=0.20,aloop=loop=-1:size=44100[aout]",
                "-map", "[vout]", "-map", "[aout]",
            ] + base_flags + [output_path]
    else:
        if has_voice:
            cmd = [
                FFMPEG, "-y",
                "-i", video_path,
                "-i", audio_path,
                "-filter_complex",
                    f"[0:v]{full_video_filter}[vout];"
                    f"[1:a]{voice_mastering}[aout]",
                "-map", "[vout]", "-map", "[aout]",
            ] + base_flags + [output_path]
        else:
            # No voice, no music — just video with silent audio
            cmd = [
                FFMPEG, "-y",
                "-i", video_path,
                "-filter_complex",
                    f"[0:v]{full_video_filter}[vout];"
                    f"anullsrc=r=44100:cl=stereo[aout]",
                "-map", "[vout]", "-map", "[aout]",
            ] + base_flags + [output_path]

    await _run_ffmpeg(cmd, "final assembly")


async def extract_thumbnail(video_path: str, output_path: str, timestamp: float = 1.5) -> str:
    """Extract thumbnail at the first punchline beat or 1.5s."""
    try:
        cmd = [
            FFMPEG, "-y",
            "-ss", str(timestamp),
            "-i", video_path,
            "-vframes", "1",
            "-q:v", "2",
            "-vf", f"scale={VIDEO_W}:{VIDEO_H}",
            output_path,
        ]
        await _run_ffmpeg(cmd, "thumbnail extraction")
        log.info(f"Thumbnail extracted: {output_path}")
        return output_path
    except Exception as e:
        log.warning(f"Thumbnail extraction failed: {e}")
        return ""


def _find_punchline_timestamp(script: dict) -> float:
    """Find the timestamp of the first punchline beat for thumbnail."""
    beats = script.get("scene_beats", [])
    for beat in beats:
        if beat.get("style") == "punchline":
            ts = float(beat.get("timestamp", 1.5))
            return max(0.5, ts)
    return 1.5


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
    Main assembly function.
    Returns (video_path, thumbnail_path).
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = output_path + "_tmp"
    Path(tmp_dir).mkdir(parents=True, exist_ok=True)

    # Determine duration from audio (or scene beat timing for silent videos)
    audio_duration = await get_audio_duration(audio_path)
    target_duration = _get_target_duration(script, audio_duration)
    log.info(f"Audio: {audio_duration:.1f}s | Target: {target_duration:.1f}s | preset: {_PRESET}")

    scene_beats = script.get("scene_beats", [])

    # Build beat-synced footage
    concat_path = os.path.join(tmp_dir, "footage.mp4")
    await _build_beat_synced_footage(
        footage_paths, scene_beats, target_duration, concat_path, tmp_dir
    )

    music_path = get_track_for_script(script)

    await _ffmpeg_assemble(
        video_path=concat_path,
        audio_path=audio_path,
        music_path=music_path,
        script=script,
        duration=target_duration,
        output_path=output_path,
        word_timings=word_timings or [],
    )

    # Thumbnail at punchline moment
    thumb_ts = _find_punchline_timestamp(script)
    thumb_path = output_path.replace(".mp4", "_thumb.jpg")
    thumb_path = await extract_thumbnail(output_path, thumb_path, timestamp=thumb_ts)

    import shutil
    shutil.rmtree(tmp_dir, ignore_errors=True)

    size_mb = os.path.getsize(output_path) / 1024 / 1024
    log.info(f"Video assembled: {output_path} ({size_mb:.1f} MB)")
    return output_path, thumb_path
