"""
TTS Engine — converts script text to speech audio.
Uses Edge-TTS (Microsoft, completely free, no API key needed).
Falls back to gTTS (Google, also free).
"""

import os, asyncio, logging, re
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

log = logging.getLogger(__name__)

FFPROBE = os.getenv("FFPROBE_PATH", "ffprobe")
EDGE_VOICE = os.getenv("TTS_VOICE", "en-US-AndrewNeural")

BACKUP_VOICES = [
    "en-US-ChristopherNeural",
    "en-US-EricNeural",
    "en-GB-RyanNeural",
]


async def generate_voiceover(text: str, output_path: str) -> str:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    clean_text = clean_for_tts(text)
    log.info(f"TTS text length: {len(clean_text)} chars")

    try:
        return await _edge_tts(clean_text, output_path)
    except Exception as e:
        log.warning(f"Edge-TTS failed: {e} — trying backup voice")

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
        rate="+14%",
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
    text = re.sub(r'\s+', ' ', text).strip()
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
