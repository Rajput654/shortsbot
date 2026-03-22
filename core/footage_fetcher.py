"""
Footage Fetcher — downloads free HD animal footage from Pexels.
Downloads 10 clips instead of 5 to ensure enough footage for 35-40s videos.
"""

import os, asyncio, logging, httpx
from pathlib import Path

log = logging.getLogger(__name__)

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
PEXELS_VIDEO_URL = "https://api.pexels.com/videos/search"

FALLBACK_TERMS = {
    "shark": ["ocean shark", "underwater fish", "ocean predator"],
    "octopus": ["underwater creature", "ocean animal", "marine life"],
    "lion": ["big cat", "wild cat africa", "savanna wildlife"],
    "elephant": ["elephant herd", "africa wildlife", "savanna animals"],
    "eagle": ["bird flight", "raptor bird", "sky bird"],
    "wolf": ["wild wolf", "forest animal", "predator animal"],
    "cheetah": ["fast cat", "africa predator", "spotted cat"],
    "whale": ["ocean whale", "blue whale ocean", "underwater giant"],
    "gorilla": ["primate jungle", "ape wildlife", "jungle animal"],
    "crocodile": ["reptile river", "crocodile water", "alligator"],
    "axolotl": ["salamander water", "aquatic animal", "underwater creature"],
    "dolphin": ["ocean dolphin", "marine mammal", "sea animal"],
    "tiger": ["big cat jungle", "wild tiger", "jungle predator"],
    "bear": ["wild bear", "grizzly bear", "forest bear"],
    "snake": ["python snake", "wild snake", "reptile animal"],
}

async def fetch_footage(animal: str, count: int = 10, output_dir: str = "output/footage") -> list[str]:
    """
    Download 10 clips by default — enough to cover 35-40s without pausing.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    if not PEXELS_API_KEY:
        log.warning("No PEXELS_API_KEY — using placeholder footage")
        return await _create_placeholder_footage(output_dir, count)

    # Search with higher per_page to get more results
    videos = await _search_pexels(animal, per_page=20)

    # Try fallbacks if not enough
    if len(videos) < count:
        fallbacks = FALLBACK_TERMS.get(animal.lower(), ["wildlife animal", "nature animal", "wild animal"])
        for term in fallbacks:
            if len(videos) >= count:
                break
            extra = await _search_pexels(term, per_page=15)
            # Avoid duplicates
            existing_urls = {v["url"] for v in videos}
            for v in extra:
                if v["url"] not in existing_urls:
                    videos.append(v)

    if not videos:
        log.warning(f"No footage found for '{animal}' — using placeholder")
        return await _create_placeholder_footage(output_dir, count)

    # Download clips — take up to `count` clips
    clips_to_download = videos[:count]
    tasks = []
    for i, video in enumerate(clips_to_download):
        file_path = os.path.join(output_dir, f"clip_{i}.mp4")
        tasks.append(_download_clip(video["url"], file_path))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    downloaded = []
    for i, result in enumerate(results):
        if isinstance(result, str):
            downloaded.append(result)
        else:
            log.warning(f"Clip {i} failed: {result}")

    log.info(f"Downloaded {len(downloaded)}/{count} clips for '{animal}'")

    # If we still don't have enough, duplicate existing clips
    if len(downloaded) < 3:
        log.warning("Very few clips downloaded — duplicating to fill video")
        while len(downloaded) < 6:
            downloaded.extend(downloaded[:3])

    return downloaded


async def _search_pexels(query: str, per_page: int = 20) -> list[dict]:
    headers = {"Authorization": PEXELS_API_KEY}
    params = {
        "query": query,
        "per_page": per_page,
        "orientation": "portrait",
        "size": "medium"
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(PEXELS_VIDEO_URL, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()

        videos = []
        for v in data.get("videos", []):
            best_file = _pick_best_file(v.get("video_files", []))
            if best_file:
                videos.append({
                    "url": best_file["link"],
                    "duration": v.get("duration", 8),
                    "width": best_file.get("width", 0),
                    "height": best_file.get("height", 0),
                })
        log.info(f"Pexels '{query}': {len(videos)} videos found")
        return videos

    except Exception as e:
        log.error(f"Pexels search failed for '{query}': {e}")
        return []


def _pick_best_file(files: list) -> dict | None:
    portrait = [f for f in files if f.get("height", 0) > f.get("width", 0)]
    candidates = portrait if portrait else files
    hd = [f for f in candidates if 540 <= f.get("height", 0) <= 1080]
    if hd:
        return sorted(hd, key=lambda x: x.get("height", 0), reverse=True)[0]
    if candidates:
        return sorted(candidates, key=lambda x: x.get("height", 0), reverse=True)[0]
    return None


async def _download_clip(url: str, path: str) -> str:
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            with open(path, "wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=8192):
                    f.write(chunk)
    log.debug(f"Downloaded: {path}")
    return path


async def _create_placeholder_footage(output_dir: str, count: int) -> list[str]:
    colors = ["0x1a3a1a", "0x0d1f2d", "0x1a1a0d", "0x2d0d1a", "0x0d2d2d",
              "0x1a0d2d", "0x2d1a0d", "0x0d2d1a", "0x2d0d2d", "0x1a2d0d"]
    paths = []
    for i in range(count):
        path = os.path.join(output_dir, f"clip_{i}.mp4")
        color = colors[i % len(colors)]
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"color=c={color}:size=720x1280:rate=30",
            "-t", "8",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await proc.wait()
        paths.append(path)
    return paths
