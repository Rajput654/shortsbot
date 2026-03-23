"""
AnimalShortsBot — Full Automation Pipeline

Flow:
  1. Generate 1 script (each cron run = 1 video)
  2. Build video → upload immediately
  3. Done

Run 4x daily via separate cron jobs (see daily_shorts.yml).
Each run = 1 video at a different time for better algorithm spread.
"""

import os, sys, asyncio, logging
from datetime import datetime
import pytz
from dotenv import load_dotenv
load_dotenv()

from core.script_generator import generate_scripts
from core.tts_engine import generate_voiceover
from core.footage_fetcher import fetch_footage
from core.video_assembler import assemble_video
from core.youtube_uploader import upload_to_youtube

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
    """Build one video and upload it immediately."""
    title = script["title"]
    log.info(f"\n{'━'*45}")
    log.info(f"[{index+1}] Starting: {title}")
    log.info(f"{'━'*45}")

    try:
        # Step 1 — Voiceover
        log.info(f"[{index+1}] 🎙  Generating voiceover...")
        audio_path = await generate_voiceover(
            text=f"{script['hook']} {script['body']} {script['cta']}",
            output_path=f"output/audio_{index}.mp3"
        )
        log.info(f"[{index+1}] ✅ Voiceover done")

        # Step 2 — Footage
        log.info(f"[{index+1}] 📹 Fetching footage: {script['animal_keyword']}")
        footage_paths = await fetch_footage(
            animal=script["animal_keyword"],
            count=10,
            output_dir=f"output/footage_{index}"
        )
        log.info(f"[{index+1}] ✅ {len(footage_paths)} clips downloaded")

        # Step 3 — Assemble
        log.info(f"[{index+1}] 🎞  Assembling video...")
        video_path = await assemble_video(
            footage_paths=footage_paths,
            audio_path=audio_path,
            script=script,
            output_path=f"output/short_{index}.mp4"
        )
        log.info(f"[{index+1}] ✅ Video assembled: {video_path}")

        # Step 4 — Upload immediately
        log.info(f"[{index+1}] 📤 Uploading now...")

        # Description optimised for Engaged Views (comments + shares = algorithm signal)
        description = (
            f"{script['hook']}\n\n"
            f"{script['body']}\n\n"
            f"💬 {script.get('cta', 'Drop your answer in the comments!')}\n\n"
            f"📲 Share this with someone who'd never believe it\n\n"
            f"🔔 Subscribe — new wild animal fact every day\n\n"
            f"⚠️ AI-generated voiceover | Footage: Pexels (free commercial license)\n\n"
            f"{' '.join(script.get('tags', []))}"
        )

        video_id = await upload_to_youtube(
            video_path=video_path,
            title=script["title"],
            description=description,
            tags=script.get("tags", [])
        )
        log.info(f"[{index+1}] ✅ LIVE: https://youtube.com/shorts/{video_id}")
        return True

    except Exception as e:
        log.error(f"[{index+1}] ❌ Failed: {e}")
        return False


async def main():
    log.info("🤖 AnimalShortsBot starting...")
    log.info(f"📅 {now_ist()}")

    # Each cron run generates and uploads 1 video
    log.info(f"\n{'━'*45}")
    log.info(f"🧠 Generating {VIDEOS_PER_DAY} script(s)...")
    log.info(f"{'━'*45}")
    scripts = await generate_scripts(count=VIDEOS_PER_DAY)
    log.info(f"✅ {len(scripts)} script(s) ready")

    results = []
    for i, script in enumerate(scripts):
        success = await build_and_upload(script, i)
        results.append(success)

    # Summary
    passed = sum(results)
    log.info(f"\n{'━'*45}")
    log.info(f"🎉 Done: {passed}/{len(scripts)} videos uploaded")
    log.info(f"📅 {now_ist()}")
    log.info(f"{'━'*45}")


if __name__ == "__main__":
    asyncio.run(main())
