"""
AnimalShortsBot — Full Automation Pipeline

Correct flow:
  1. START → Generate all 4 scripts immediately
  2. START → Build all 4 videos immediately (voiceover + footage + assemble)
  3. WAIT  → Sleep until 8:00 AM IST  → Upload video 1
  4. WAIT  → Sleep until 12:00 PM IST → Upload video 2
  5. WAIT  → Sleep until 6:00 PM IST  → Upload video 3
  6. WAIT  → Sleep until 9:00 PM IST  → Upload video 4

Run once in the morning — bot handles everything.
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
VIDEOS_PER_DAY = int(os.getenv("VIDEOS_PER_DAY", "4"))

# Upload times in IST (hour, minute, label)
UPLOAD_SCHEDULE = [
    (8,  0,  "Morning commute"),
    (12, 0,  "Lunch break"),
    (18, 0,  "Evening peak ⭐"),
    (21, 0,  "Night scroll"),
]


def now_ist() -> datetime:
    return datetime.now(IST)


def seconds_until(hour: int, minute: int) -> float:
    """Seconds until next occurrence of this IST time."""
    now = now_ist()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    diff = (target - now).total_seconds()
    if diff < 0:
        diff += 86400  # Time already passed today — wait until tomorrow
    return diff


def format_wait(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h}h {m}m {s}s"


async def build_one_video(script: dict, index: int) -> str | None:
    """
    Build a single video completely:
    voiceover → footage → assemble → return path
    """
    log.info(f"[{index+1}] 🎙  Generating voiceover...")
    try:
        audio_path = await generate_voiceover(
            text=f"{script['hook']} {script['body']} {script['cta']}",
            output_path=f"output/audio_{index}.mp3"
        )
        log.info(f"[{index+1}] ✅ Voiceover done")

        log.info(f"[{index+1}] 📹 Fetching footage: {script['animal_keyword']}")
        footage_paths = await fetch_footage(
            animal=script["animal_keyword"],
            count=10,
            output_dir=f"output/footage_{index}"
        )
        log.info(f"[{index+1}] ✅ {len(footage_paths)} clips downloaded")

        log.info(f"[{index+1}] 🎞  Assembling video...")
        video_path = await assemble_video(
            footage_paths=footage_paths,
            audio_path=audio_path,
            script=script,
            output_path=f"output/short_{index}.mp4"
        )
        log.info(f"[{index+1}] ✅ Video built: {video_path}")
        return video_path

    except Exception as e:
        log.error(f"[{index+1}] ❌ Build failed: {e}")
        return None


async def upload_one_video(video_path: str, script: dict, index: int) -> bool:
    """Upload a ready video to YouTube."""
    try:
        description = (
            f"{script['hook']}\n\n"
            f"{script['body']}\n\n"
            f"🔔 Subscribe for daily animal facts!\n\n"
            f"⚠️ AI-generated voiceover | Footage: Pexels free license\n\n"
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
        log.error(f"[{index+1}] ❌ Upload failed: {e}")
        return False


async def main():
    log.info("🤖 AnimalShortsBot starting...")
    log.info(f"📅 {now_ist().strftime('%Y-%m-%d %H:%M IST')}")

    # ── PHASE 1: Generate all scripts ─────────────────────────────────
    log.info(f"\n{'━'*45}")
    log.info("🧠 PHASE 1: Generating all scripts...")
    log.info(f"{'━'*45}")
    scripts = await generate_scripts(count=VIDEOS_PER_DAY)
    log.info(f"✅ {len(scripts)} scripts ready")

    # ── PHASE 2: Build ALL videos right now ───────────────────────────
    log.info(f"\n{'━'*45}")
    log.info("🎬 PHASE 2: Building all videos now...")
    log.info(f"{'━'*45}")

    built_videos = []  # list of (video_path or None, script)

    for i, script in enumerate(scripts):
        log.info(f"\n--- Building video {i+1}/{len(scripts)}: {script['title']} ---")
        video_path = await build_one_video(script, i)
        built_videos.append((video_path, script))

    # Count how many built successfully
    success_count = sum(1 for v, _ in built_videos if v is not None)
    log.info(f"\n✅ Built {success_count}/{len(scripts)} videos successfully")

    # ── PHASE 3: Wait and upload at scheduled times ───────────────────
    log.info(f"\n{'━'*45}")
    log.info("📅 PHASE 3: Waiting to upload at scheduled times...")
    log.info(f"{'━'*45}")

    # Print full schedule
    for i, (hour, minute, label) in enumerate(UPLOAD_SCHEDULE[:len(built_videos)]):
        wait = seconds_until(hour, minute)
        video_path, script = built_videos[i]
        status = "✅ Ready" if video_path else "❌ Failed to build"
        log.info(f"  Video {i+1} → {hour:02d}:{minute:02d} IST ({label}) — {format_wait(wait)} from now — {status}")

    log.info("")

    upload_results = []

    for i, (video_path, script) in enumerate(built_videos):
        if i >= len(UPLOAD_SCHEDULE):
            break

        hour, minute, label = UPLOAD_SCHEDULE[i]

        if video_path is None:
            log.warning(f"[{i+1}] Skipping — video failed to build")
            upload_results.append(False)
            continue

        # Wait until exact upload time
        wait_secs = seconds_until(hour, minute)

        if wait_secs > 30:
            log.info(f"[{i+1}] ⏳ Video {i+1} is ready and waiting...")
            log.info(f"[{i+1}] 🕐 Will upload at {hour:02d}:{minute:02d} IST ({label})")
            log.info(f"[{i+1}] ⏳ Time remaining: {format_wait(wait_secs)}")
            await asyncio.sleep(wait_secs)

        # Upload now
        log.info(f"\n{'━'*45}")
        log.info(f"📤 {now_ist().strftime('%H:%M IST')} — Uploading video {i+1}: {script['title']}")
        log.info(f"{'━'*45}")
        success = await upload_one_video(video_path, script, i)
        upload_results.append(success)

        # Small gap before next wait cycle
        await asyncio.sleep(10)

    # ── Final summary ─────────────────────────────────────────────────
    passed = sum(upload_results)
    log.info(f"\n{'━'*45}")
    log.info(f"🎉 ALL DONE: {passed}/{len(built_videos)} videos uploaded today")
    log.info(f"📅 {now_ist().strftime('%Y-%m-%d %H:%M IST')}")
    log.info(f"{'━'*45}")


if __name__ == "__main__":
    asyncio.run(main())
