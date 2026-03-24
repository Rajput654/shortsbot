"""
AnimalShortsBot — Full Automation Pipeline v2.1

UPDATES v2.1:
- TTS text construction updated to include 'shock_word' and 'loop_hook'.
- Ensuring the 'Loop Hook' is the final audio piece to bridge back to the start.
- Directory safety checks added for the 'output/' folder.
"""

import os, sys, asyncio, logging
from pathlib import Path
from datetime import datetime
import pytz
from dotenv import load_dotenv
load_dotenv()

from core.script_generator import generate_scripts
from core.tts_engine import generate_voiceover_with_timings
from core.footage_fetcher import fetch_footage
from core.video_assembler import assemble_video
from core.youtube_uploader import upload_to_youtube
from core.analytics_fetcher import (
    fetch_analytics_for_ready_videos,
    add_to_upload_queue,
    get_performance_summary
)
from core.youtube_scanner import scan_channel_and_update_tracker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger(__name__)

IST = pytz.timezone("Asia/Kolkata")
VIDEOS_PER_DAY = int(os.getenv("VIDEOS_PER_DAY", "1"))

def now_ist() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")

async def build_and_upload(script: dict, index: int) -> bool:
    title = script["title"]
    # Ensure output directory exists to prevent FileNotFoundError
    Path("output").mkdir(exist_ok=True)
    
    log.info(f"\n{'━'*45}")
    log.info(f"[{index+1}] Starting: {title}")
    log.info(f"[{index+1}] Mode: {script.get('length_mode', 'long')} | Animal: {script.get('animal_keyword', '?')}")
    log.info(f"{'━'*45}")

    try:
        # VIRAL UPDATE: Constructing the full narration string
        # We include the shock_word (usually yelled) and the loop_hook (at the very end)
        full_narration = (
            f"{script['hook']} {script.get('shock_word', '')}. "
            f"{script['body']} {script['cta']} {script.get('loop_hook', '')}"
        )

        # Step 1 — Voiceover + word timings
        log.info(f"[{index+1}] Generating voiceover (including Loop Hook bridge)...")
        audio_path, word_timings = await generate_voiceover_with_timings(
            text=full_narration,
            output_path=f"output/audio_{index}.mp3"
        )

        # Step 2 — Footage
        log.info(f"[{index+1}] Fetching footage: {script['animal_keyword']}")
        # Ensure we use the correct function name from your core module
        footage_paths = await fetch_footage(
            animal=script["animal_keyword"],
            count=10
        )

        # Step 3 — Assemble with synced captions + loop + visual style
        log.info(f"[{index+1}] Assembling video with Viral Filters...")
        video_path = await assemble_video(
            footage_paths=footage_paths,
            audio_path=audio_path,
            script=script,
            output_path=f"output/short_{index}.mp4",
            word_timings=word_timings,
        )

        # Step 4 — Build description (remains unchanged)
        all_tags = script.get("tags", []) + script.get("seo_tags", [])
        unique_tags = list(dict.fromkeys(all_tags))
        description = _build_description(script, unique_tags)

        # Step 5 — Upload
        log.info(f"[{index+1}] Uploading to YouTube...")
        video_id = await upload_to_youtube(
            video_path=video_path,
            title=script["title"],
            description=description,
            tags=unique_tags,
            pinned_comment=script.get("pinned_comment", "")
        )
        log.info(f"[{index+1}] LIVE: https://youtube.com/shorts/{video_id}")

        # Step 6 — Register for analytics
        add_to_upload_queue(video_id, script)
        return True

    except Exception as e:
        log.error(f"[{index+1}] Pipeline failed: {e}", exc_info=True)
        return False

# ... [Keep existing _build_description and main() functions] ...
