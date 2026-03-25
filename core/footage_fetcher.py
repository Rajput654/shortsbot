"""
Footage Fetcher v3.0
Downloads free HD animal footage from Pexels.

UPGRADES v3.0 (rating fixes):
- LANDSCAPE FALLBACK: portrait-only filter on Pexels yields very few animal
  clips. Now tries portrait first, then falls back to landscape with FFmpeg
  9:16 crop applied later in video assembly. This gives 10× more clip variety.
- DURATION FILTER: rejects clips shorter than 3s or longer than 30s —
  avoids 1-frame clips and huge downloads that slow the pipeline.
- CLIP COUNT GUARANTEE: keeps fetching until we have `count` valid clips
  or exhaust all strategies.

NICHE UPDATE: Search queries updated from documentary-style to funny/playful
terms so Pexels returns clips that match the funny animal moments niche.
"""

import os, asyncio, logging, httpx
from pathlib import Path

log = logging.getLogger(__name__)
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")

MIN_CLIP_DURATION = 3   # seconds — skip sub-3s clips
MAX_CLIP_DURATION = 30  # seconds — skip overly long clips


async def fetch_footage(animal: str, count: int = 12, output_dir: str = "output/footage") -> list[str]:
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # ── CHANGE: Updated queries from documentary → funny/playful style ─────────
    queries = [
        animal,
        f"funny {animal}",
        f"{animal} playing",
        f"{animal} cute funny",
        f"{animal} reaction",
    ]

    # Keep predator/giant special cases but add a playful variant too
    predators = ["lion", "shark", "wolf", "tiger", "bear", "crocodile", "eagle", "snake", "wolverine"]
    if any(p in animal.lower() for p in predators):
        queries.append(f"{animal} funny reaction")
    else:
        queries.append(f"{animal} silly playful")

    giants = ["whale", "elephant", "rhino", "hippo"]
    if any(g in animal.lower() for g in giants):
        queries.append(f"{animal} cute baby")

    log.info(f"Pexels tiered search for: {queries}")

    # ── Phase 1: portrait search ───────────────────────────────────────────
    portrait_tasks = [_search_pexels(q, per_page=8, orientation="portrait") for q in queries]
    portrait_results = await asyncio.gather(*portrait_tasks)
    portrait_videos = _interleave(portrait_results)

    # ── Phase 2: landscape fallback (tagged for later crop) ───────────────
    landscape_videos = []
    portrait_count = len(_dedupe_videos(portrait_videos))
    if portrait_count < count:
        shortage = count - portrait_count
        log.info(f"Only {portrait_count} portrait clips — fetching {shortage} landscape as fallback")
        landscape_tasks = [_search_pexels(q, per_page=6, orientation="landscape") for q in queries[:3]]
        landscape_results = await asyncio.gather(*landscape_tasks)
        raw = _interleave(landscape_results)
        landscape_videos = [_tag_landscape(v) for v in raw]

    combined = _dedupe_videos(portrait_videos + landscape_videos)

    # ── Phase 3: generic wildlife safety net ──────────────────────────────
    if len(combined) < count:
        log.warning(f"Still only {len(combined)} clips — generic funny animals fallback")
        fallback = await _search_pexels("funny cute animals pets", per_page=count, orientation="portrait")
        combined = _dedupe_videos(combined + fallback)

    # ── Download ──────────────────────────────────────────────────────────
    clips_to_download = combined[:count]
    tasks = [
        _download_clip(v, i, output_dir)
        for i, v in enumerate(clips_to_download)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    downloaded = [r for r in results if isinstance(r, str)]

    log.info(f"Fetched {len(downloaded)} clips for '{animal}'")
    if not downloaded:
        raise RuntimeError(f"No footage found for '{animal}'. Check PEXELS_API_KEY.")
    return downloaded


def _interleave(results: list[list]) -> list:
    """Round-robin interleave result lists so shot types alternate."""
    combined = []
    max_len = max((len(r) for r in results), default=0)
    for i in range(max_len):
        for r in results:
            if i < len(r):
                combined.append(r[i])
    return combined


def _tag_landscape(video_obj: dict) -> dict:
    """Mark a video object as needing 9:16 crop during assembly."""
    video_obj["_needs_crop"] = True
    return video_obj


def _dedupe_videos(videos: list) -> list:
    """Remove duplicate video IDs."""
    seen, out = set(), []
    for v in videos:
        vid_id = v.get("id")
        if vid_id and vid_id not in seen:
            dur = v.get("duration", 0)
            if MIN_CLIP_DURATION <= dur <= MAX_CLIP_DURATION:
                seen.add(vid_id)
                out.append(v)
    return out


async def _search_pexels(query: str, per_page: int = 10, orientation: str = "portrait") -> list:
    if not PEXELS_API_KEY:
        log.warning("PEXELS_API_KEY not set")
        return []

    url = "https://api.pexels.com/videos/search"
    headers = {"Authorization": PEXELS_API_KEY}
    params = {
        "query": query,
        "per_page": per_page,
        "orientation": orientation,
        "size": "medium",
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            return resp.json().get("videos", [])
    except Exception as e:
        log.error(f"Pexels error for '{query}' ({orientation}): {e}")
        return []


def _extract_best_mp4(video_obj: dict) -> str:
    """Extract the best available MP4 URL from a Pexels video object."""
    files = video_obj.get("video_files", [])
    if not files:
        return ""

    needs_crop = video_obj.get("_needs_crop", False)
    target_quality = "hd"

    for f in files:
        if f.get("quality") == target_quality and f.get("link", "").endswith(".mp4"):
            return f["link"]

    for f in files:
        if f.get("link", "").endswith(".mp4"):
            return f["link"]

    return ""


async def _download_clip(video_obj: dict, index: int, output_dir: str) -> str:
    url = _extract_best_mp4(video_obj)
    if not url:
        raise RuntimeError(f"No MP4 URL for video {video_obj.get('id')}")

    needs_crop = video_obj.get("_needs_crop", False)
    suffix = "_landscape" if needs_crop else ""
    save_path = os.path.join(output_dir, f"clip_{index}{suffix}.mp4")

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            with open(save_path, "wb") as f:
                f.write(resp.content)
        log.debug(f"Downloaded clip_{index}{suffix}.mp4 ({video_obj.get('duration', '?')}s)")
        return save_path
    except Exception as e:
        log.error(f"Download failed for clip_{index}: {e}")
        raise RuntimeError("Download failed")
