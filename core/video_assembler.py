"""
Video Assembler — combines footage, voiceover, captions, and music.
VIRAL UPDATES: 
- Audio Sidechaining: Music automatically ducks when the voiceover speaks.
- High-Speed Pacing: Visual resets every 2 seconds to maximize retention.
- Cinema Polish: Added Vignette and high-bitrate mastering.
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
    """
    VIRAL REFINEMENT: Alternating Punch-In / Punch-Out cuts.
    Resets zoom every 2 seconds to maintain extreme visual momentum.
    """
    concat_file = os.path.join(tmp_dir, "concat.txt")
    lines = []
    accumulated = 0.0
    idx = 0
    buffer = target_duration + 5.0

    while accumulated < buffer:
        clip = footage_paths[idx % len(footage_paths)]
        safe = os.path.abspath(clip).replace("\\", "/")
        lines.append(f"file '{safe}'")
        accumulated += 8.0 
        idx += 1

    with open(concat_file, "w") as f:
        f.write("\n".join(lines))

    # UPGRADED: 2-second visual reset + Vignette for 'Documentary' feel
    dynamic_cut_filter = (
        f"scale=1280:2276,crop=720:1280," 
        f"zoompan=z='if(lte(mod(time,2),1), min(zoom+0.002,1.2), max(zoom-0.002,1.0))'"
        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={VIDEO_W}x{VIDEO_H}:fps=30,"
        f"vignette=PI/4"
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
    font = FONT_PATH if os.path.exists(FONT_PATH) else ""

    # Viral Retention: 1-word rapid fire captions
    caption_chunks = group_into_chunks(word_timings, chunk_size=1)
    caption_filter = build_caption_drawtext(caption_chunks, font, VIDEO_H, VIDEO_W)
    
    # Seamless Loop: Involuntary rewatch trigger
    xfade_duration = 0.3
    xfade_offset = max(duration - xfade_duration - 0.1, duration * 0.85)
    loop_filter = (
        f"[0:v]split[v1][v2];"
        f"[v1]trim=0:{xfade_offset + xfade_duration}[va];"
        f"[v2]trim={xfade_offset}:{duration},setpts=PTS-STARTPTS[vb];"
        f"[va][vb]xfade=transition=fade:duration={xfade_duration}:offset={xfade_offset}[vlooped]"
    )

    # Audio Mastering: Bass boost + Sidechain Compression (Music ducks for voice)
    voice_mastering = "bass=g=6:f=110,compand=attacks=0:points=-80/-80|-15/-15|0/-10.8|20/-5.2,volume=1.2"

    if music_path and os.path.exists(music_path):
        cmd = [
            FFMPEG, "-y",
            "-i", video_path,
            "-i", audio_path,
            "-i", music_path,
            "-filter_complex",
                f"{loop_filter};"
                f"[vlooped]{caption_filter}[vout];"
                f"[1:a]{voice_mastering}[voice];"
                f"[2:a]volume=0.1,aloop=loop=-1:size=44100[music_loop];"
                f"[music_loop][voice]sidechaincompress=threshold=0.15:ratio=20:release=200[music_ducked];"
                f"[voice][music_ducked]amix=inputs=2:duration=first[aout]",
            "-map", "[vout]", "-map", "[aout]",
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-c:a", "aac", "-b:a", AUDIO_BITRATE,
            "-movflags", "+faststart",
            output_path
        ]
        await _run_ffmpeg(cmd, "final assembly")
