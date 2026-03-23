"""
Analytics Fetcher — pulls view/like/comment/engaged-view counts from YouTube
48 hours after upload and writes them to performance_log.json.

UPDATES v2:
- engagedViewCount is now the PRIMARY optimization signal (not viewCount).
  Since March 2025, YouTube's algorithm rewards engaged views — watch sessions
  where the viewer was active — not raw loops. This is what script_generator.py
  uses to decide which hook/CTA styles to replicate or avoid.
- engaged_view_rate calculated as engagedViewCount / impressions (not likes/views)
- performance_log.json schema updated with engaged_views field
- script_generator feedback prompt updated to surface engaged_view_rate

performance_log.json schema (v2):
{
  "videos": [
    {
      "video_id": "abc123",
      "title": "...",
      "animal": "mantis shrimp",
      "hook_type": "wrong_fact",
      "cta_type": "B",
      "length_mode": "long",
      "upload_date": "2026-03-22 15:11",
      "fetched_date": "2026-03-24 15:11",
      "views": 45230,
      "engaged_views": 38100,
      "likes": 1820,
      "comments": 342,
      "engaged_view_rate": 0.842,
      "like_rate": 0.040
    }
  ],
  "last_updated": "2026-03-24 15:11"
}
"""

import os, json, logging, asyncio
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

PERFORMANCE_LOG = os.path.join(os.path.dirname(__file__), "..", "performance_log.json")
UPLOAD_QUEUE = os.path.join(os.path.dirname(__file__), "..", "upload_queue.json")


def _load_log() -> dict:
    if os.path.exists(PERFORMANCE_LOG):
        try:
            with open(PERFORMANCE_LOG, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"videos": [], "last_updated": ""}


def _save_log(data: dict):
    data["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(PERFORMANCE_LOG, "w") as f:
        json.dump(data, f, indent=2)
    log.info(f"Performance log saved: {len(data['videos'])} entries")


def _load_queue() -> list:
    if os.path.exists(UPLOAD_QUEUE):
        try:
            with open(UPLOAD_QUEUE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_queue(queue: list):
    with open(UPLOAD_QUEUE, "w") as f:
        json.dump(queue, f, indent=2)


def add_to_upload_queue(video_id: str, script: dict):
    """Called immediately after upload to register for future analytics fetch."""
    queue = _load_queue()
    entry = {
        "video_id": video_id,
        "title": script.get("title", ""),
        "animal": script.get("animal_keyword", ""),
        "hook_type": script.get("hook_type", "unknown"),
        "cta_type": script.get("cta_type", "unknown"),
        "length_mode": script.get("length_mode", "long"),
        "upload_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "fetch_after": (datetime.now() + timedelta(hours=48)).strftime("%Y-%m-%d %H:%M")
    }
    queue.append(entry)
    _save_queue(queue)
    log.info(f"Added to analytics queue: {video_id} (fetch after 48h)")


def fetch_analytics_for_ready_videos():
    """
    Check upload queue for videos 48h+ old and fetch their analytics.
    Uses engagedViewCount as primary KPI alongside raw views.
    """
    queue = _load_queue()
    if not queue:
        return

    now = datetime.now()
    ready = []
    still_waiting = []

    for entry in queue:
        try:
            fetch_after = datetime.strptime(entry["fetch_after"], "%Y-%m-%d %H:%M")
            if now >= fetch_after:
                ready.append(entry)
            else:
                still_waiting.append(entry)
        except Exception:
            still_waiting.append(entry)

    if not ready:
        log.info(f"Analytics: {len(still_waiting)} videos still in 48h wait window")
        return

    log.info(f"Fetching analytics for {len(ready)} videos...")

    try:
        fetched = _fetch_from_youtube([e["video_id"] for e in ready])
    except Exception as e:
        log.warning(f"YouTube analytics fetch failed: {e}")
        return

    perf_log = _load_log()

    for entry in ready:
        vid_id = entry["video_id"]
        stats = fetched.get(vid_id, {})

        views = int(stats.get("viewCount", 0))
        engaged_views = int(stats.get("engagedViewCount", 0))
        likes = int(stats.get("likeCount", 0))
        comments = int(stats.get("commentCount", 0))

        # Primary signal: what % of raw views were engaged views
        engaged_view_rate = round(engaged_views / max(views, 1), 4)
        # Secondary: like rate (likes per view)
        like_rate = round(likes / max(views, 1), 4)

        record = {
            "video_id": vid_id,
            "title": entry.get("title", ""),
            "animal": entry.get("animal", ""),
            "hook_type": entry.get("hook_type", "unknown"),
            "cta_type": entry.get("cta_type", "unknown"),
            "length_mode": entry.get("length_mode", "long"),
            "upload_date": entry.get("upload_date", ""),
            "fetched_date": now.strftime("%Y-%m-%d %H:%M"),
            "views": views,
            "engaged_views": engaged_views,
            "likes": likes,
            "comments": comments,
            "engaged_view_rate": engaged_view_rate,
            "like_rate": like_rate,
        }

        perf_log["videos"].append(record)
        log.info(
            f"Analytics logged: {entry.get('title','?')} | "
            f"{views:,} views | {engaged_views:,} engaged | "
            f"EVR: {engaged_view_rate:.1%} | {likes:,} likes"
        )

    _save_log(perf_log)
    _save_queue(still_waiting)
    log.info(f"Analytics fetch complete. {len(still_waiting)} videos still pending.")


def _fetch_from_youtube(video_ids: list[str]) -> dict:
    """
    Fetch stats for a list of video IDs.
    Requests both 'statistics' and 'contentDetails' parts.
    engagedViewCount is in statistics since YouTube API v3 March 2025 update.
    Returns {video_id: stats_dict}.
    """
    from googleapiclient.discovery import build
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    creds_json = os.getenv("YT_CREDENTIALS")
    if not creds_json:
        raise ValueError("YT_CREDENTIALS not set")

    creds_data = json.loads(creds_json)
    creds = Credentials(
        token=creds_data.get("token"),
        refresh_token=creds_data["refresh_token"],
        token_uri=creds_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=creds_data["client_id"],
        client_secret=creds_data["client_secret"],
        scopes=["https://www.googleapis.com/auth/youtube.readonly"]
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)

    results = {}
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i+50]
        response = youtube.videos().list(
            part="statistics",
            id=",".join(batch)
        ).execute()

        for item in response.get("items", []):
            vid_id = item["id"]
            results[vid_id] = item.get("statistics", {})

    return results


def get_performance_summary() -> str:
    """Return a human-readable performance summary for logging."""
    data = _load_log()
    videos = data.get("videos", [])
    if not videos:
        return "No performance data yet."

    total = len(videos)
    views_list = [v.get("views", 0) for v in videos]
    evr_list = [v.get("engaged_view_rate", 0) for v in videos if v.get("engaged_view_rate", 0) > 0]
    avg_views = sum(views_list) / max(total, 1)
    avg_evr = sum(evr_list) / max(len(evr_list), 1)
    best = max(videos, key=lambda v: v.get("engaged_views", v.get("views", 0)))

    return (
        f"Performance: {total} videos | "
        f"Avg views: {avg_views:,.0f} | "
        f"Avg engaged view rate: {avg_evr:.1%} | "
        f"Best: '{best.get('title','?')}' ({best.get('engaged_views', best.get('views',0)):,} engaged views)"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from dotenv import load_dotenv
    load_dotenv()
    fetch_analytics_for_ready_videos()
    print(get_performance_summary())
