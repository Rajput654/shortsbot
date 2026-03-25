"""
AnimalShortsBot — Full Automation Pipeline v3.0

UPGRADES v3.0:
- Uses prepare_script_text() from tts_engine for shock_word emphasis + CTA pause.
- assemble_video() now returns (video_path, thumbnail_path) — thumbnail is
  uploaded to YouTube for better Browse/Search CTR.
- build_description() moved to youtube_uploader for cleaner separation.
- trending_audio.ensure_default_track() called at startup.
- All v3 module changes are wired up here.
"""

import os, sys, asyncio, logging
from pathlib import Path
from datetime import datetime
import pytz
from dotenv import load_dotenv
load_dotenv()

from core.script_generator import generate_scripts
from core.tts_engine import generate_voiceover_with_timings, prepare_script_text
from core.footage_fetcher import fetch_footage
from core.video_assembler import assemble_video
from core.youtube_uploader import upload_to_youtube, build_description
from core.analytics_fetcher import (
    fetch_analytics_for_ready_videos,
    add_to_upload_queue,
    get_performance_summary,
)
from core.youtube_scanner import scan_channel_and_update_tracker
from core.trending_audio import ensure_default_track

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

IST = pytz.timezone("Asia/Kolkata")
VIDEOS_PER_DAY = int(os.getenv("VIDEOS_PER_DAY", "1"))


def now_ist() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")


async def build_and_upload(script: dict, index: int) -> bool:
    title = script["title"]
    Path("output").mkdir(exist_ok=True)

    log.info(f"\n{'━'*50}")
    log.info(f"[{index+1}] Starting: {title}")
    log.info(f"[{index+1}] Mode: {script.get('length_mode', 'long')} | Animal: {script.get('animal_keyword', '?')}")
    log.info(f"{'━'*50}")

    try:
        # Step 1 — Build narration with shock_word emphasis + CTA pause
        full_narration = prepare_script_text(script)

        # Step 2 — Voiceover + word timings
        log.info(f"[{index+1}] Generating voiceover...")
        audio_path, word_timings = await generate_voiceover_with_timings(
            text=full_narration,
            output_path=f"output/audio_{index}.mp3",
        )

        # Step 3 — Footage (landscape fallback handled inside fetcher)
        log.info(f"[{index+1}] Fetching footage: {script['animal_keyword']}")
        footage_paths = await fetch_footage(
            animal=script["animal_keyword"],
            count=10,
        )

        # Step 4 — Assemble video + extract thumbnail
        log.info(f"[{index+1}] Assembling video...")
        video_path, thumb_path = await assemble_video(
            footage_paths=footage_paths,
            audio_path=audio_path,
            script=script,
            output_path=f"output/short_{index}.mp4",
            word_timings=word_timings,
        )

        # Step 5 — Build description
        all_tags    = script.get("tags", []) + script.get("seo_tags", [])
        unique_tags = list(dict.fromkeys(all_tags))
        description = build_description(script, unique_tags)

        # Step 6 — Upload with thumbnail
        log.info(f"[{index+1}] Uploading to YouTube...")
        video_id = await upload_to_youtube(
            video_path=video_path,
            title=script["title"],
            description=description,
            tags=unique_tags,
            pinned_comment=script.get("pinned_comment", ""),
            thumbnail_path=thumb_path,
        )
        log.info(f"[{index+1}] LIVE: https://youtube.com/shorts/{video_id}")

        # Step 7 — Register for analytics
        add_to_upload_queue(video_id, script)
        return True

    except Exception as e:
        log.error(f"[{index+1}] Pipeline failed: {e}", exc_info=True)
        return False


async def main():
    log.info(f"{'='*55}")
    log.info(f"AnimalShortsBot v3.0 starting at {now_ist()}")
    log.info(f"Videos this run: {VIDEOS_PER_DAY}")
    log.info(f"{'='*55}")

    # ── Pre-run setup ──────────────────────────────────────────────────────
    ensure_default_track()           # Download default music if missing
    fetch_analytics_for_ready_videos()  # Pull 48h+ analytics from YouTube
    log.info(get_performance_summary())

    # Sync channel so animal tracker is always up-to-date
    try:
        scan_channel_and_update_tracker()
    except Exception as e:
        log.warning(f"Channel scan failed (non-fatal): {e}")

    # ── Generate scripts ───────────────────────────────────────────────────
    log.info(f"Generating {VIDEOS_PER_DAY} script(s)...")
    scripts = await generate_scripts(count=VIDEOS_PER_DAY)
    log.info(f"Scripts ready: {len(scripts)}")

    # ── Build & upload ─────────────────────────────────────────────────────
    results = []
    for i, script in enumerate(scripts):
        ok = await build_and_upload(script, i)
        results.append(ok)

    # ── Summary ────────────────────────────────────────────────────────────
    success = sum(results)
    failed  = len(results) - success
    log.info(f"\n{'='*55}")
    log.info(f"Run complete at {now_ist()}")
    log.info(f"Uploaded: {success} | Failed: {failed}")
    log.info(f"{'='*55}")


if __name__ == "__main__":
    asyncio.run(main())
