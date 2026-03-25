"""
Analytics Fetcher v3.0

UPGRADES v3.0 (rating fixes):
- HOOK_TYPE WIN-RATE TABLE: get_hook_type_summary() builds a formatted table
  of EVR by hook_type, injected into the script_generator prompt so the AI
  replicates what's actually working on YOUR channel.
- LENGTH_MODE COMPARISON: get_length_mode_summary() compares short vs long EVR
  so script_generator can pick the winning format automatically.
- Both functions are imported by script_generator.py.
"""

import os, json, logging, asyncio
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

PERFORMANCE_LOG = os.path.join(os.path.dirname(__file__), "..", "performance_log.json")
UPLOAD_QUEUE    = os.path.join(os.path.dirname(__file__), "..", "upload_queue.json")


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
    queue = _load_queue()
    entry = {
        "video_id":    video_id,
        "title":       script.get("title", ""),
        "animal":      script.get("animal_keyword", ""),
        "hook_type":   script.get("hook_type", "unknown"),
        "cta_type":    script.get("cta_type", "unknown"),
        "length_mode": script.get("length_mode", "long"),
        "upload_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "fetch_after": (datetime.now() + timedelta(hours=48)).strftime("%Y-%m-%d %H:%M"),
    }
    queue.append(entry)
    _save_queue(queue)
    log.info(f"Added to analytics queue: {video_id}")


def get_hook_type_summary() -> str:
    """
    Returns a formatted EVR table by hook_type for prompt injection.
    Used by script_generator to bias hook selection toward what works.
    """
    data   = _load_log()
    videos = data.get("videos", [])
    if len(videos) < 4:
        return ""

    evr_by_type: dict[str, list[float]] = {}
    for v in videos:
        ht  = v.get("hook_type", "unknown")
        evr = v.get("engaged_view_rate", 0)
        if ht and evr > 0:
            evr_by_type.setdefault(ht, []).append(evr)

    if not evr_by_type:
        return ""

    rows = []
    for ht, evrs in sorted(evr_by_type.items(), key=lambda x: -sum(x[1])/len(x[1])):
        avg  = sum(evrs) / len(evrs)
        rows.append(f"  {ht:<18} avg EVR: {avg:.1%}  (n={len(evrs)})")

    return "HOOK TYPE PERFORMANCE (your channel):\n" + "\n".join(rows)


def get_length_mode_summary() -> str:
    """Returns short vs long EVR comparison string for prompt injection."""
    data   = _load_log()
    videos = data.get("videos", [])
    if len(videos) < 4:
        return ""

    short_evrs = [v["engaged_view_rate"] for v in videos if v.get("length_mode") == "short" and v.get("engaged_view_rate", 0) > 0]
    long_evrs  = [v["engaged_view_rate"] for v in videos if v.get("length_mode") == "long"  and v.get("engaged_view_rate", 0) > 0]

    lines = []
    if short_evrs:
        lines.append(f"  short (13s): avg EVR {sum(short_evrs)/len(short_evrs):.1%} (n={len(short_evrs)})")
    if long_evrs:
        lines.append(f"  long  (55s): avg EVR {sum(long_evrs)/len(long_evrs):.1%} (n={len(long_evrs)})")

    return ("LENGTH MODE PERFORMANCE:\n" + "\n".join(lines)) if lines else ""


def fetch_analytics_for_ready_videos():
    queue = _load_queue()
    if not queue:
        return

    now            = datetime.now()
    ready          = []
    still_waiting  = []

    for entry in queue:
        try:
            fetch_after = datetime.strptime(entry["fetch_after"], "%Y-%m-%d %H:%M")
            (ready if now >= fetch_after else still_waiting).append(entry)
        except Exception:
            still_waiting.append(entry)

    if not ready:
        log.info(f"Analytics: {len(still_waiting)} videos in 48h wait")
        return

    log.info(f"Fetching analytics for {len(ready)} videos...")

    try:
        fetched = _fetch_from_youtube([e["video_id"] for e in ready])
    except Exception as e:
        log.warning(f"YouTube analytics fetch failed: {e}")
        return

    perf_log = _load_log()

    for entry in ready:
        vid_id        = entry["video_id"]
        stats         = fetched.get(vid_id, {})
        views         = int(stats.get("viewCount", 0))
        engaged_views = int(stats.get("engagedViewCount", 0))
        likes         = int(stats.get("likeCount", 0))
        comments      = int(stats.get("commentCount", 0))

        evr       = round(engaged_views / max(views, 1), 4)
        like_rate = round(likes / max(views, 1), 4)

        record = {
            "video_id":          vid_id,
            "title":             entry.get("title", ""),
            "animal":            entry.get("animal", ""),
            "hook_type":         entry.get("hook_type", "unknown"),
            "cta_type":          entry.get("cta_type", "unknown"),
            "length_mode":       entry.get("length_mode", "long"),
            "upload_date":       entry.get("upload_date", ""),
            "fetched_date":      now.strftime("%Y-%m-%d %H:%M"),
            "views":             views,
            "engaged_views":     engaged_views,
            "likes":             likes,
            "comments":          comments,
            "engaged_view_rate": evr,
            "like_rate":         like_rate,
        }

        perf_log["videos"].append(record)
        log.info(
            f"Analytics: {entry.get('title','?')} | "
            f"{views:,} views | EVR: {evr:.1%} | {likes:,} likes"
        )

    _save_log(perf_log)
    _save_queue(still_waiting)


def _fetch_from_youtube(video_ids: list[str]) -> dict:
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
        scopes=["https://www.googleapis.com/auth/youtube.readonly"],
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
    results = {}

    for i in range(0, len(video_ids), 50):
        batch    = video_ids[i:i+50]
        response = youtube.videos().list(part="statistics", id=",".join(batch)).execute()
        for item in response.get("items", []):
            results[item["id"]] = item.get("statistics", {})

    return results


def get_performance_summary() -> str:
    data   = _load_log()
    videos = data.get("videos", [])
    if not videos:
        return "No performance data yet."

    total      = len(videos)
    avg_views  = sum(v.get("views", 0) for v in videos) / max(total, 1)
    evr_list   = [v["engaged_view_rate"] for v in videos if v.get("engaged_view_rate", 0) > 0]
    avg_evr    = sum(evr_list) / max(len(evr_list), 1)
    best       = max(videos, key=lambda v: v.get("engaged_views", v.get("views", 0)))

    return (
        f"Performance: {total} videos | "
        f"Avg views: {avg_views:,.0f} | "
        f"Avg EVR: {avg_evr:.1%} | "
        f"Best: '{best.get('title','?')}' ({best.get('engaged_views', best.get('views',0)):,} engaged views)\n"
        f"{get_hook_type_summary()}\n"
        f"{get_length_mode_summary()}"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from dotenv import load_dotenv
    load_dotenv()
    fetch_analytics_for_ready_videos()
    print(get_performance_summary())
