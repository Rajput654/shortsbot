"""
TTS Engine — converts script text to speech audio.
Uses Edge-TTS (Microsoft, completely free, no API key needed).
Falls back to gTTS (Google, also free).

UPDATES v2:
- generate_voiceover_with_timings() — new primary function that returns
  BOTH the audio path AND word-level timing data in one call.
  This avoids running TTS twice (once for audio, once for boundaries).
- Primary: en-US-BrianNeural (warm, energetic)
- Rate +8% — natural speed for Shorts
- Word boundary capture is baked in alongside audio save
"""

import os, asyncio, logging, re
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

log = logging.getLogger(__name__)

FFPROBE = os.getenv("FFPROBE_PATH", "ffprobe")

EDGE_VOICE = os.getenv("TTS_VOICE", "en-US-BrianNeural")

BACKUP_VOICES = [
    "en-US-EmmaMultilingualNeural",
    "en-GB-RyanNeural",
    "en-US-ChristopherNeural",
    "en-US-EricNeural",
]

# 100-nanosecond ticks per second (Edge-TTS uses Windows FILETIME units)
TICKS_PER_SECOND = 10_000_000


async def generate_voiceover_with_timings(text: str, output_path: str) -> tuple[str, list[dict]]:
    """
    PRIMARY function — generates voiceover AND captures word-level timings
    in a single TTS pass. More efficient than running TTS twice.

    Returns:
        (audio_path, word_timings)
        word_timings: list of {word, start, end} dicts with times in seconds
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    clean_text = clean_for_tts(text)

    try:
        return await _edge_tts_with_timings(clean_text, output_path)
    except Exception as e:
        log.warning(f"Edge-TTS primary failed: {e} — trying backup voices")

    for voice in BACKUP_VOICES:
        try:
            return await _edge_tts_with_timings(clean_text, output_path, voice=voice)
        except Exception as e:
            log.warning(f"Backup voice {voice} failed: {e}")

    # Final fallback — no timings available
    log.warning("Falling back to gTTS (no word timings available)")
    path = await _gtts(clean_text, output_path)
    return path, []


async def generate_voiceover(text: str, output_path: str) -> str:
    """Legacy wrapper — returns only the audio path."""
    path, _ = await generate_voiceover_with_timings(text, output_path)
    return path


async def _edge_tts_with_timings(
    text: str, output_path: str, voice: str = EDGE_VOICE
) -> tuple[str, list[dict]]:
    """
    Run Edge-TTS, save audio AND capture WordBoundary events in one pass.
    Edge-TTS streams audio chunks and metadata events simultaneously.
    """
    import edge_tts

    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate="+8%",
        volume="+0%",
        pitch="+0Hz"
    )

    tmp_path = output_path + ".tmp.mp3"
    boundaries = []

    with open(tmp_path, "wb") as f:
        async for event in communicate.stream():
            if event["type"] == "audio":
                f.write(event["data"])
            elif event["type"] == "WordBoundary":
                start_sec = event["offset"] / TICKS_PER_SECOND
                duration_sec = event["duration"] / TICKS_PER_SECOND
                word = event.get("text", "").strip()
                if word:
                    boundaries.append({
                        "word": word.upper(),
                        "start": round(start_sec, 3),
                        "end": round(start_sec + duration_sec, 3),
                    })

    os.replace(tmp_path, output_path)
    log.info(f"Edge-TTS success: {voice} — {len(boundaries)} word boundaries captured → {output_path}")
    return output_path, boundaries


async def _gtts(text: str, output_path: str) -> str:
    import gtts
    def _run():
        tts = gtts.gTTS(text=text, lang="en", slow=False)
        tts.save(output_path)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _run)
    log.info(f"gTTS fallback success → {output_path}")
    return output_path


def clean_for_tts(text: str) -> str:
    """
    Clean text AND add natural speech patterns.
    Edge-TTS reads punctuation as breath/pause cues.
    """
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

    text = re.sub(
        r'\b(wait for it|but wait|here\'s the thing|get this|ready for this)\b',
        r'... \1 ...',
        text, flags=re.IGNORECASE
    )
    text = re.sub(
        r'\b(yes really|yes, really|no really|seriously)\b',
        r'... \1',
        text, flags=re.IGNORECASE
    )
    text = re.sub(r'(\d+) (times|miles|feet|pounds|tons|mph|kmh)', r'\1, \2', text)
    text = re.sub(r'(that\'?s? like )', r'— \1', text, flags=re.IGNORECASE)
    text = re.sub(r'\b(And here\'?s? the crazy part|The insane part is|The wild thing is)\b',
                  r'... \1', text, flags=re.IGNORECASE)

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
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        import json
        data = json.loads(stdout)
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "audio":
                return float(stream.get("duration", 60))
    except Exception as e:
        log.warning(f"ffprobe failed: {e} — using default 60s duration")
    return 60.0
