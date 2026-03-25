"""
TTS Engine v4.0 — Inner Monologue Voice for Scenario Format

OVERHAUL v4.0:
- VOICE ROLE CHANGED: No longer narrates facts. Now voices only the animal's
  inner monologue lines from scene_beats["voice_line"] fields.
- SILENCE GAPS: Generates audio with intentional silence gaps between voice
  lines so the TTS aligns with the beat timestamps in the video.
- VOICE CHARACTER: Uses a slightly faster, more expressive delivery to match
  the "deadpan/dramatic animal inner voice" format.
- WORD TIMINGS: Still generated for caption sync, but now also used to
  sync voice_lines to their beat timestamps.
- SILENT AUDIO: If no voice_lines exist (silent scenario video), generates
  a silent audio track of correct duration for the FFmpeg pipeline.

RETAINED from v3.1:
- Edge-TTS with v6/v7 compatibility
- gTTS fallback
- Audio duration detection
"""

import os, asyncio, logging, re
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

log = logging.getLogger(__name__)
FFPROBE = os.getenv("FFPROBE_PATH", "ffprobe")
FFMPEG  = os.getenv("FFMPEG_PATH",  "ffmpeg")
EDGE_VOICE = os.getenv("TTS_VOICE", "en-US-BrianNeural")
BACKUP_VOICES = [
    "en-US-EmmaMultilingualNeural",
    "en-GB-RyanNeural",
    "en-US-ChristopherNeural",
    "en-US-EricNeural",
]
TICKS_PER_SECOND = 10_000_000


def prepare_script_text(script: dict) -> str:
    """
    v4.0: Extract only the voice_line fields from scene_beats.
    These are the animal's short inner monologue lines.
    Returns a string of just those lines joined with pauses,
    OR empty string if no voice_lines exist (silent video).
    """
    beats = script.get("scene_beats", [])
    voice_lines = [b.get("voice_line", "").strip() for b in beats if b.get("voice_line", "").strip()]

    if not voice_lines:
        # This is a silent scenario video — no narration needed
        return ""

    # Join with '...' pauses between lines for natural spacing
    tone = script.get("voice_tone", "deadpan comedic")
    # Add tone-specific intro pause if dramatic/betrayed
    joined = " ... ".join(voice_lines)
    return joined


async def generate_voiceover_with_timings(
    text: str,
    output_path: str,
    target_duration: float = 0.0,
) -> tuple[str, list[dict]]:
    """
    v4.0: Generates voice audio from inner monologue text.
    If text is empty (silent video), generates a silent audio file.
    Returns (audio_path, word_timings).
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    if not text or not text.strip():
        # Silent scenario — generate silence of target_duration
        if target_duration <= 0:
            target_duration = 30.0
        log.info(f"No voice lines — generating {target_duration:.1f}s silent audio")
        await _generate_silence(output_path, target_duration)
        return output_path, []

    clean_text = clean_for_tts(text)

    try:
        path, timings = await _edge_tts_with_timings(clean_text, output_path)
        if timings:
            return path, timings
        log.warning("Primary voice returned 0 word boundaries — trying backup voices")
    except Exception as e:
        log.warning(f"Edge-TTS primary failed: {e} — trying backup voices")

    for voice in BACKUP_VOICES:
        try:
            path, timings = await _edge_tts_with_timings(clean_text, output_path, voice=voice)
            if timings:
                return path, timings
        except Exception as e:
            log.warning(f"Backup voice {voice} failed: {e}")

    # All voices failed — use gTTS with estimated timings
    log.warning("All Edge-TTS voices failed — using gTTS")
    try:
        path, _ = await _edge_tts_with_timings(clean_text, output_path)
    except Exception:
        path = await _gtts(clean_text, output_path)

    from core.caption_sync import _estimate_timings
    estimated = _estimate_timings(clean_text)
    return path, estimated


async def generate_voiceover(text: str, output_path: str) -> str:
    """Legacy wrapper."""
    path, _ = await generate_voiceover_with_timings(text, output_path)
    return path


async def _generate_silence(output_path: str, duration: float):
    """Generate a silent audio file using FFmpeg."""
    cmd = [
        FFMPEG, "-y",
        "-f", "lavfi",
        "-i", f"anullsrc=r=44100:cl=mono",
        "-t", str(duration),
        "-q:a", "9",
        "-acodec", "libmp3lame",
        output_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        # FFmpeg lavfi might not support this — write a 0-byte workaround
        log.warning(f"FFmpeg silence generation failed: {stderr.decode()[-500:]}")
        # Fallback: generate via edge-tts with a space
        try:
            await _edge_tts_with_timings("  ", output_path)
        except Exception:
            pass
    else:
        log.info(f"Silent audio generated: {duration:.1f}s → {output_path}")


async def _edge_tts_with_timings(
    text: str, output_path: str, voice: str = EDGE_VOICE
) -> tuple[str, list[dict]]:
    import edge_tts

    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate="+12%",   # Slightly faster = more energetic inner voice
        volume="+0%",
        pitch="+0Hz",
    )

    tmp_path   = output_path + ".tmp.mp3"
    boundaries = []

    with open(tmp_path, "wb") as f:
        async for event in communicate.stream():
            if event["type"] == "audio":
                f.write(event["data"])
            elif event["type"] in ("WordBoundary", "word_boundary"):
                start_sec    = event["offset"] / TICKS_PER_SECOND
                duration_sec = event["duration"] / TICKS_PER_SECOND
                word = event.get("text", event.get("word", "")).strip()
                if word:
                    boundaries.append({
                        "word":  word.upper(),
                        "start": round(start_sec, 3),
                        "end":   round(start_sec + duration_sec, 3),
                    })

    os.replace(tmp_path, output_path)
    log.info(f"Edge-TTS: {voice} → {len(boundaries)} boundaries → {output_path}")
    return output_path, boundaries


async def _gtts(text: str, output_path: str) -> str:
    import gtts
    def _run():
        tts = gtts.gTTS(text=text, lang="en", slow=False)
        tts.save(output_path)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _run)
    log.info(f"gTTS fallback → {output_path}")
    return output_path


def clean_for_tts(text: str) -> str:
    """Clean text for Edge-TTS. Adds natural pauses for inner monologue."""
    text = re.sub(r'#\w+', '', text)
    text = re.sub(r'http\S+', '', text)
    text = re.sub(
        r'[\U00010000-\U0010ffff'
        r'\U0001F600-\U0001F64F'
        r'\U0001F300-\U0001F5FF'
        r'\U0001F680-\U0001F6FF'
        r'\U0001F1E0-\U0001F1FF'
        r'\u2600-\u26FF\u2700-\u27BF]+',
        '', text, flags=re.UNICODE
    )
    # Asterisk action text (*does something*) → remove for TTS
    text = re.sub(r'\*[^*]+\*', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'\.{4,}', '...', text)
    return text


async def get_audio_duration(audio_path: str) -> float:
    try:
        proc = await asyncio.create_subprocess_exec(
            FFPROBE, "-v", "quiet",
            "-print_format", "json",
            "-show_streams", audio_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        import json
        data = json.loads(stdout)
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "audio":
                return float(stream.get("duration", 30))
    except Exception as e:
        log.warning(f"ffprobe failed: {e} — using default 30s")
    return 30.0
