"""
TTS Engine v3.0 — text-to-speech with word-level timing.

UPGRADES v3.0 (rating fixes):
- SHOCK_WORD EMPHASIS: inject a dramatic pause before the shock_word and
  slow its rate slightly so Edge-TTS reads it with natural stress.
  Edge-TTS doesn't support SSML, but rate/pause tags in SSML-like syntax
  ARE processed by edge-tts >= 6.1.9 via the communicate rate/pitch params.
  We instead inject '...' pauses around the shock_word in the text itself.
- PRE-CTA PAUSE: inject a longer pause (', ...') before the CTA text so
  the call-to-action lands after a beat, not rushed against the body.
- Both transformations happen in prepare_script_text(), called from main.py.
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
TICKS_PER_SECOND = 10_000_000


def prepare_script_text(script: dict) -> str:
    """
    Build the final narration string from a script dict.
    Injects pauses around shock_word and before CTA for natural delivery.
    Called from main.py instead of constructing the string inline.
    """
    hook      = script.get("hook", "")
    shock     = script.get("shock_word", "")
    body      = script.get("body", "")
    cta       = script.get("cta", "")
    loop_hook = script.get("loop_hook", "")

    # Inject dramatic pause around shock_word in body text
    if shock and shock in body:
        # "...IMPOSSIBLE..." → "... IMPOSSIBLE ..."
        body = body.replace(shock, f"... {shock} ...")

    # Add a beat before the CTA so it lands cleanly
    cta_with_pause = f"... {cta}"

    narration = f"{hook} {shock}. {body}{cta_with_pause} {loop_hook}"
    return narration


async def generate_voiceover_with_timings(text: str, output_path: str) -> tuple[str, list[dict]]:
    """
    PRIMARY function — generates voiceover AND word-level timings in one pass.
    Returns (audio_path, word_timings).
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

    log.warning("Falling back to gTTS (no word timings)")
    path = await _gtts(clean_text, output_path)
    return path, []


async def generate_voiceover(text: str, output_path: str) -> str:
    """Legacy wrapper — returns only audio path."""
    path, _ = await generate_voiceover_with_timings(text, output_path)
    return path


async def _edge_tts_with_timings(
    text: str, output_path: str, voice: str = EDGE_VOICE
) -> tuple[str, list[dict]]:
    import edge_tts

    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate="+8%",
        volume="+0%",
        pitch="+0Hz",
    )

    tmp_path  = output_path + ".tmp.mp3"
    boundaries = []

    with open(tmp_path, "wb") as f:
        async for event in communicate.stream():
            if event["type"] == "audio":
                f.write(event["data"])
            elif event["type"] == "WordBoundary":
                start_sec    = event["offset"] / TICKS_PER_SECOND
                duration_sec = event["duration"] / TICKS_PER_SECOND
                word         = event.get("text", "").strip()
                if word:
                    boundaries.append({
                        "word": word.upper(),
                        "start": round(start_sec, 3),
                        "end": round(start_sec + duration_sec, 3),
                    })

    os.replace(tmp_path, output_path)
    log.info(f"Edge-TTS: {voice} → {len(boundaries)} word boundaries → {output_path}")
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
    """Clean text and inject natural pause markers for Edge-TTS."""
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
        r'... \1 ...', text, flags=re.IGNORECASE
    )
    text = re.sub(r'\b(yes really|no really|seriously)\b', r'... \1', text, flags=re.IGNORECASE)
    text = re.sub(r'(\d+) (times|miles|feet|pounds|tons|mph|kmh)', r'\1, \2', text)
    text = re.sub(r'(that\'?s? like )', r'— \1', text, flags=re.IGNORECASE)
    text = re.sub(
        r'\b(And here\'?s? the crazy part|The insane part is|The wild thing is)\b',
        r'... \1', text, flags=re.IGNORECASE
    )
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
                return float(stream.get("duration", 60))
    except Exception as e:
        log.warning(f"ffprobe failed: {e} — using default 60s")
    return 60.0
