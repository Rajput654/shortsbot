"""
AnimalShortsBot — Full Automation Pipeline v4.0

CHANGES v4.0:
- Pipeline now uses scenario/POV format instead of AI narrator facts.
- Voice generation uses script["voice_narration"] (inner monologue only).
- Duration is derived from scene_beats, not just audio length.
- Description and title updated to reflect scenario format.
- All v4 module changes wired up.
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


def _get_beat_duration(script: dict) -> float:
    """Get the expected video duration from scene beats."""
    beats = script.get("scene_beats", [])
    if beats:
        last_ts = max(b.get("timestamp", 0) for b in beats)
        return last_ts + 3.5
    return 30.0


async def build_and_upload(script: dict, index: int) -> bool:
    title = script["title"]
    format_type = script.get("format_type", "pov")
    Path("output").mkdir(exist_ok=True)

    log.info(f"\n{'━'*55}")
    log.info(f"[{index+1}] Starting: {title}")
    log.info(f"[{index+1}] Format: {format_type} | Animal: {script.get('animal_keyword', '?')}")
    log.info(f"[{index+1}] Beats: {len(script.get('scene_beats', []))} | "
             f"Voice: {script.get('voice_style', 'none')}")
    log.info(f"{'━'*55}")

    try:
        # Step 1 — Get voice narration (inner monologue only, may be empty)
        voice_narration = script.get("voice_narration", "")
        beat_duration = _get_beat_duration(script)

        if voice_narration.strip():
            log.info(f"[{index+1}] Generating inner monologue voiceover...")
            audio_path, word_timings = await generate_voiceover_with_timings(
                text=voice_narration,
                output_path=f"output/audio_{index}.mp3",
                target_duration=beat_duration,
            )
        else:
            log.info(f"[{index+1}] Silent scenario — generating silent audio track...")
            audio_path, word_timings = await generate_voiceover_with_timings(
                text="",  # triggers silent audio generation
                output_path=f"output/audio_{index}.mp3",
                target_duration=beat_duration,
            )

        # Step 2 — Footage
        log.info(f"[{index+1}] Fetching footage: {script['animal_keyword']}")
        footage_paths = await fetch_footage(
            animal=script["animal_keyword"],
            count=12,  # More clips for beat-synced editing
        )

        # Step 3 — Assemble with beat-synced text overlays
        log.info(f"[{index+1}] Assembling scenario video...")
        video_path, thumb_path = await assemble_video(
            footage_paths=footage_paths,
            audio_path=audio_path,
            script=script,
            output_path=f"output/short_{index}.mp4",
            word_timings=word_timings,
        )

        # Step 4 — Description
        all_tags    = script.get("seo_tags", [])
        unique_tags = list(dict.fromkeys(all_tags))
        description = build_description(script, unique_tags)

        # Step 5 — Upload
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

        add_to_upload_queue(video_id, script)
        return True

    except Exception as e:
        log.error(f"[{index+1}] Pipeline failed: {e}", exc_info=True)
        return False


async def main():
    log.info(f"{'='*55}")
    log.info(f"AnimalShortsBot v4.0 — Scenario Format")
    log.info(f"Starting at {now_ist()}")
    log.info(f"Videos this run: {VIDEOS_PER_DAY}")
    log.info(f"{'='*55}")

    ensure_default_track()
    fetch_analytics_for_ready_videos()
    log.info(get_performance_summary())

    try:
        scan_channel_and_update_tracker()
    except Exception as e:
        log.warning(f"Channel scan failed (non-fatal): {e}")

    log.info(f"Generating {VIDEOS_PER_DAY} script(s)...")
    scripts = await generate_scripts(count=VIDEOS_PER_DAY)
    log.info(f"Scripts ready: {len(scripts)}")

    results = []
    for i, script in enumerate(scripts):
        ok = await build_and_upload(script, i)
        results.append(ok)

    success = sum(results)
    failed  = len(results) - success
    log.info(f"\n{'='*55}")
    log.info(f"Run complete at {now_ist()}")
    log.info(f"Uploaded: {success} | Failed: {failed}")
    log.info(f"{'='*55}")


if __name__ == "__main__":
    asyncio.run(main())
