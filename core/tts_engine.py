"""
TTS Engine — converts script text to speech audio.
Uses Edge-TTS (Microsoft, completely free, no API key needed).
Falls back to gTTS (Google, also free).

VOICE UPGRADE:
- Primary: en-US-BrianNeural (warm, energetic, less robotic than Andrew)
- Backup 1: en-US-EmmaMultilingualNeural (very natural female voice)
- Backup 2: en-GB-RyanNeural (least robotic, natural emphasis)
- Rate slowed slightly from +14% to +8% — Brian already speaks fast,
  and slower = more human, better retention on Shorts.
"""

import os, asyncio, logging, re
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

log = logging.getLogger(__name__)

FFPROBE = os.getenv("FFPROBE_PATH", "ffprobe")

# PRIMARY VOICE — Brian is warmer and more energetic than Andrew
EDGE_VOICE = os.getenv("TTS_VOICE", "en-US-BrianNeural")

# Fallback chain — ordered by naturalness
BACKUP_VOICES = [
    "en-US-EmmaMultilingualNeural",  # Very natural, multilingual
    "en-GB-RyanNeural",               # Least robotic per community feedback
    "en-US-ChristopherNeural",        # Good energy
    "en-US-EricNeural",               # Clean fallback
]


async def generate_voiceover(text: str, output_path: str) -> str:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    clean_text = clean_for_tts(text)
    log.info(f"TTS text length: {len(clean_text)} chars")
    log.info(f"TTS preview: {clean_text[:120]}...")

    try:
        return await _edge_tts(clean_text, output_path)
    except Exception as e:
        log.warning(f"Edge-TTS primary failed: {e} — trying backup voices")

    for voice in BACKUP_VOICES:
        try:
            return await _edge_tts(clean_text, output_path, voice=voice)
        except Exception as e:
            log.warning(f"Backup voice {voice} failed: {e}")

    log.warning("Falling back to gTTS...")
    return await _gtts(clean_text, output_path)


async def _edge_tts(text: str, output_path: str, voice: str = EDGE_VOICE) -> str:
    import edge_tts
    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate="+8%",     # Slightly faster than default but not rushed — sounds natural
        volume="+0%",
        pitch="+0Hz"
    )
    tmp_path = output_path + ".tmp.mp3"
    await communicate.save(tmp_path)
    os.replace(tmp_path, output_path)
    log.info(f"Edge-TTS success: {voice} → {output_path}")
    return output_path


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
    
    Key insight: Edge-TTS reads punctuation as breath/pause cues.
    - Commas = short pause (natural breath)
    - Ellipsis (...) = longer dramatic pause
    - Exclamation = rising energy
    - Em dash (—) = mid-sentence pause/pivot
    
    We strip hashtags/URLs/emojis but KEEP and ENHANCE punctuation
    to make the voice sound more human and less like a robot reading.
    """
    # Remove hashtags
    text = re.sub(r'#\w+', '', text)
    # Remove URLs
    text = re.sub(r'http\S+', '', text)
    # Remove emojis
    text = re.sub(
        r'[\U00010000-\U0010ffff'
        r'\U0001F600-\U0001F64F'
        r'\U0001F300-\U0001F5FF'
        r'\U0001F680-\U0001F6FF'
        r'\U0001F1E0-\U0001F1FF'
        r'\u2600-\u26FF\u2700-\u27BF]+',
        '', text, flags=re.UNICODE
    )

    # ── Naturalness enhancements ──────────────────────────────────────────

    # "Wait for it" beats — add dramatic pause before reveal
    text = re.sub(
        r'\b(wait for it|but wait|here\'s the thing|get this|ready for this)\b',
        r'... \1 ...',
        text, flags=re.IGNORECASE
    )

    # "Yes really" confirmation — add slight pause before
    text = re.sub(
        r'\b(yes really|yes, really|no really|seriously)\b',
        r'... \1',
        text, flags=re.IGNORECASE
    )

    # Numbers with units — add comma after big numbers to force slight pause
    # e.g. "23 times" → "23, times" feels more punchy when spoken
    text = re.sub(r'(\d+) (times|miles|feet|pounds|tons|mph|kmh)', r'\1, \2', text)

    # "That is like" comparisons — add em dash for emphasis
    text = re.sub(r'(that\'?s? like )', r'— \1', text, flags=re.IGNORECASE)

    # Transition phrases — natural pause
    text = re.sub(r'\b(And here\'?s? the crazy part|The insane part is|The wild thing is)\b',
                  r'... \1', text, flags=re.IGNORECASE)

    # Clean up multiple spaces/newlines
    text = re.sub(r'\s+', ' ', text).strip()

    # Clean up triple+ dots to exactly three
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
