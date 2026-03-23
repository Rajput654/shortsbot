"""
AnimalShortsBot — Full Automation Pipeline

UPDATES:
- Channel scanner runs at startup: fetches ALL videos from your YouTube channel,
  extracts animal names from titles, and adds them to used_animals.json.
  This ensures zero duplicates even if the tracker was reset or videos were
  uploaded manually.
- Pinned comment posted after every upload
- Niche SEO tags included in description and YouTube tags array
- Analytics fetcher runs at start of each pipeline run (fetches 48h-old videos)
- Video registered in upload queue for future analytics fetch
- Performance feedback loop feeds into next script generation cycle
- Trending audio auto-selected per script energy level
- Thumbnail title-card frame baked into first 0.5s of every video
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
    """Build one video and upload it immediately."""
    title = script["title"]
    log.info(f"\n{'━'*45}")
    log.info(f"[{index+1}] Starting: {title}")
    log.info(f"[{index+1}] Mode: {script.get('length_mode', 'long')} | Animal: {script.get('animal_keyword', '?')}")
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

        # Step 3 — Assemble (thumbnail frame + caption background + trending audio)
        log.info(f"[{index+1}] 🎞  Assembling video...")
        video_path = await assemble_video(
            footage_paths=footage_paths,
            audio_path=audio_path,
            script=script,
            output_path=f"output/short_{index}.mp4"
        )
        log.info(f"[{index+1}] ✅ Video assembled: {video_path}")

        # Step 4 — Build description with niche SEO tags
        # Combine generic tags + niche-specific SEO tags from script
        all_tags = script.get("tags", []) + script.get("seo_tags", [])
        unique_tags = list(dict.fromkeys(all_tags))  # preserve order, remove dupes

        description = _build_description(script, unique_tags)

        # Step 5 — Upload with pinned comment
        log.info(f"[{index+1}] 📤 Uploading now...")

        pinned_comment = script.get("pinned_comment", "")

        video_id = await upload_to_youtube(
            video_path=video_path,
            title=script["title"],
            description=description,
            tags=unique_tags,
            pinned_comment=pinned_comment
        )
        log.info(f"[{index+1}] ✅ LIVE: https://youtube.com/shorts/{video_id}")

        if pinned_comment:
            log.info(f"[{index+1}] 📌 Pinned: \"{pinned_comment}\"")

        # Step 6 — Register for analytics fetch (in 48h)
        add_to_upload_queue(video_id, script)
        log.info(f"[{index+1}] 📊 Registered for analytics fetch in 48h")

        return True

    except Exception as e:
        log.error(f"[{index+1}] ❌ Failed: {e}", exc_info=True)
        return False


def _build_description(script: dict, all_tags: list[str]) -> str:
    """
    Build optimised video description.
    - Niche SEO tags in description body (improves search indexing)
    - Pinned comment question echoed in description (keyword signal)
    - Standard CTAs for engagement + subscribe
    """
    # Build hashtag string from all tags (limit to avoid spam filter)
    hashtags = " ".join(t if t.startswith("#") else f"#{t}" for t in all_tags[:20])

    description = (
        f"{script['hook']}\n\n"
        f"{script['body']}\n\n"
        f"💬 {script.get('cta', 'Drop your answer in the comments!')}\n\n"
        f"📲 Share this with someone who'd never believe it\n\n"
        f"🔔 Subscribe — new wild animal fact every day\n\n"
        f"⚠️ AI-generated voiceover | Footage: Pexels (free commercial license)\n\n"
        f"{hashtags}"
    )

    return description


async def main():
    log.info("🤖 AnimalShortsBot starting...")
    log.info(f"📅 {now_ist()}")

    # ── Step 0a: Scan YouTube channel for existing animal videos ──────────
    # This syncs used_animals.json with your actual channel content.
    # Uses a cache so it only re-scans when the channel has new videos.
    log.info(f"\n{'━'*45}")
    log.info("🔍 Scanning YouTube channel for existing animals...")
    log.info(f"{'━'*45}")
    try:
        found_on_channel = scan_channel_and_update_tracker()
        if found_on_channel:
            log.info(f"✅ Channel scan done — {len(found_on_channel)} animals found on channel")
        else:
            log.info("✅ Channel scan done — no videos on channel yet (or scan skipped)")
    except Exception as e:
        log.warning(f"Channel scan failed (non-fatal, continuing): {e}")

    # ── Step 0b: Fetch analytics for any videos that are 48h+ old ─────────
    log.info(f"\n{'━'*45}")
    log.info("📊 Checking analytics queue...")
    log.info(f"{'━'*45}")
    try:
        fetch_analytics_for_ready_videos()
        log.info(get_performance_summary())
    except Exception as e:
        log.warning(f"Analytics fetch failed (non-fatal): {e}")

    # ── Step 1: Generate scripts (with performance feedback) ───────────────
    log.info(f"\n{'━'*45}")
    log.info(f"🧠 Generating {VIDEOS_PER_DAY} script(s)...")
    log.info(f"{'━'*45}")
    scripts = await generate_scripts(count=VIDEOS_PER_DAY)
    log.info(f"✅ {len(scripts)} script(s) ready")

    # ── Step 2: Build + upload each video ─────────────────────────────────
    results = []
    for i, script in enumerate(scripts):
        success = await build_and_upload(script, i)
        results.append(success)

    # ── Summary ───────────────────────────────────────────────────────────
    passed = sum(results)
    log.info(f"\n{'━'*45}")
    log.info(f"🎉 Done: {passed}/{len(scripts)} videos uploaded")
    log.info(f"📅 {now_ist()}")
    log.info(f"{'━'*45}")


if __name__ == "__main__":
    asyncio.run(main())
