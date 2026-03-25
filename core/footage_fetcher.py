"""
Footage Fetcher — The "Viral B-Roll Director"

UPDATES for 10/10 Reliability:
- Multi-layered search intent (Subject, Detail, Action).
- Strict parsing for raw .mp4 HD links (fixes the HTML download bug).
- File integrity checks to prevent FFmpeg crashes.
- Concurrency limits (Semaphore) to prevent server timeout bans.
- Automated fallback to placeholder clips if an animal is too obscure.
"""

import os, asyncio, logging, httpx
from pathlib import Path

log = logging.getLogger(__name__)

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
PEXELS_SEARCH_URL = "https://api.pexels.com/videos/search"

async def fetch_footage(animal: str, count: int = 12, output_dir: str = "output/footage") -> list[str]:
    """
    Fetches 9:16 vertical footage with multi-layered search intent and interleaving.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    if not PEXELS_API_KEY:
        log.warning("No PEXELS_API_KEY found — falling back to placeholders.")
        return await _create_placeholder_footage(output_dir, count)

    # 1. Tiered Search Queries for Visual Variety
    queries = [
        f"{animal}",                          # Primary subject
        f"{animal} close up",                 # High-detail (Hooks the viewer)
        f"{animal} wild nature",              # B-roll habitat
    ]
    
    # Add aggressive modifiers for higher retention on predators
    predators = ["lion", "shark", "wolf", "tiger", "eagle", "crocodile", "bear", "cheetah", "predator"]
    if any(p in animal.lower() for p in predators):
        queries.append(f"{animal} hunt attack")
    else:
        queries.append(f"{animal} funny cute")

    # 2. Execute searches in parallel
    search_tasks = [_search_pexels(q, per_page=15) for q in queries]
    search_results = await asyncio.gather(*search_tasks)
    
    # 3. Interleave results (Round-Robin) to prevent consecutive visually similar clips
    combined_videos = []
    max_len = max((len(res) for res in search_results), default=0)
    for i in range(max_len):
        for res_list in search_results:
            if i < len(res_list):
                combined_videos.append(res_list[i])

    # 4. De-duplicate based on the actual raw MP4 URL (Fixes the HTML download bug)
    unique_videos = []
    seen = set()
    for v in combined_videos:
        if v["mp4_url"] not in seen:
            seen.add(v["mp4_url"])
            unique_videos.append(v)

    if not unique_videos:
        log.warning(f"No Pexels footage found for '{animal}'. Using placeholders.")
        return await _create_placeholder_footage(output_dir, count)

    # 5. Download with Concurrency Limits (Prevents timeouts on free tiers)
    clips_to_download = unique_videos[:count]
    semaphore = asyncio.Semaphore(3)  # Max 3 concurrent downloads so we don't get banned

    async def sem_download(video_data, index):
        async with semaphore:
            path = os.path.join(output_dir, f"clip_{index}.mp4")
            return await _download_clip(video_data["mp4_url"], path)

    tasks = [sem_download(video, i) for i, video in enumerate(clips_to_download)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    downloaded = [r for r in results if isinstance(r, str)]
    
    # 6. Final safety check: duplicate clips if we didn't get enough to fill the video
    if downloaded and len(downloaded) < 4:
        log.warning("Very few clips fetched. Duplicating available clips to fill runtime.")
        while len(downloaded) < count and len(downloaded) < 12:
            downloaded.extend(downloaded[: (count - len(downloaded))])

    log.info(f"✅ Fetched {len(downloaded)} verified HD clips for '{animal}'.")
    return downloaded

async def _search_pexels(query: str, per_page: int = 15) -> list[dict]:
    """Search Pexels and extract raw .mp4 links."""
    headers = {"Authorization": PEXELS_API_KEY}
    params = {
        "query": query,
        "per_page": per_page,
        "orientation": "portrait", # Enforce vertical algorithm favorability
        "size": "medium"
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(PEXELS_SEARCH_URL, headers=headers, params=params)
            if resp.status_code == 429:
                log.warning("Pexels Rate Limit Hit!")
                return []
            resp.raise_for_status()
            data = resp.json()
            
        videos = []
        for v in data.get("videos", []):
            # VIRAL FIX: Parse the actual video files array, not the webpage URL
            best_file = _pick_best_file(v.get("video_files", []))
            if best_file:
                videos.append({
                    "mp4_url": best_file["link"],
                    "duration": v.get("duration", 8),
                })
        return videos
    except Exception as e:
        log.warning(f"Search failed for '{query}': {str(e)}")
        return []

def _pick_best_file(files: list) -> dict | None:
    """Finds the best HD portrait .mp4 link from the Pexels file array."""
    # Prioritize portrait (height > width)
    portrait = [f for f in files if f.get("height", 0) > f.get("width", 0)]
    candidates = portrait if portrait else files
    
    # Look for standard Shorts HD (1920x1080 or close)
    hd = [f for f in candidates if 720 <= f.get("height", 0) <= 2160]
    
    if hd:
        return sorted(hd, key=lambda x: x.get("height", 0), reverse=True)[0]
    if candidates:
        return sorted(candidates, key=lambda x: x.get("height", 0), reverse=True)[0]
    return None

async def _download_clip(url: str, path: str) -> str | Exception:
    """Downloads the raw .mp4 and verifies integrity."""
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with open(path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=8192):
                        f.write(chunk)
        
        # Integrity Check: Ensure file isn't empty (corrupted)
        if os.path.getsize(path) < 10000: # Less than 10KB is definitely not a video
            raise ValueError("Downloaded file is too small/corrupted.")
            
        return path
    except Exception as e:
        log.error(f"Download failed for {url[:30]}... : {e}")
        return e

async def _create_placeholder_footage(output_dir: str, count: int) -> list[str]:
    """Failsafe mechanism to ensure the bot never crashes if footage is missing."""
    colors = ["0x1a3a1a", "0x0d1f2d", "0x1a1a0d", "0x2d0d1a", "0x0d2d2d"]
    paths = []
    for i in range(count):
        path = os.path.join(output_dir, f"clip_placeholder_{i}.mp4")
        color = colors[i % len(colors)]
        
        # Uses FFmpeg to generate a 5-second solid color video
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c={color}:size=720x1280:rate=30",
            "-t", "5", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await proc.wait()
        paths.append(path)
        
    log.info(f"Generated {count} fallback placeholder clips.")
    return paths
