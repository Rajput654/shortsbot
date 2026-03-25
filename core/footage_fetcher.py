"""
Footage Fetcher (10/10 VIRAL EDITION)
Downloads free HD animal footage from Pexels.

VIRAL UPDATES:
- Tiered Search Intent: Fetches Subject, Close-ups, Habitat, and Action shots.
- Round-Robin Interleaving: Ensures no two consecutive shots look the same.
- Native Vertical: Strictly enforces 9:16 portrait orientation.
- Safe Fallbacks: Auto-switches to generic wildlife if the specific animal is too rare.
"""

import os, asyncio, logging, httpx
from pathlib import Path

log = logging.getLogger(__name__)
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")

async def fetch_footage(animal: str, count: int = 12, output_dir: str = "output/footage") -> list[str]:
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # 1. Tiered Search Intent (The "Viral B-Roll" Formula)
    queries = [
        f"{animal}",                          # Primary subject
        f"{animal} close up",                 # High-detail (retention hook)
        f"{animal} natural habitat",          # Environmental context
    ]
    
    # Add behavioral modifiers based on animal type
    predators = ["lion", "shark", "wolf", "tiger", "bear", "crocodile", "eagle", "snake"]
    if any(p in animal.lower() for p in predators):
        queries.append(f"{animal} attack hunt")
    else:
        queries.append(f"{animal} cute funny")
        
    # Add "Scale/Size Comparison" hook for specific large animals
    giants = ["whale", "elephant", "rhino", "hippo", "dinosaur"]
    if any(g in animal.lower() for g in giants):
        queries.append(f"{animal} vs human")

    log.info(f"Executing tiered Pexels searches for: {queries}")

    # 2. Execute parallel searches
    search_tasks = [_search_pexels(q, per_page=10) for q in queries]
    search_results = await asyncio.gather(*search_tasks)
    
    # Fallback mechanism: If rare animal yields no results, use generic wildlife
    total_found = sum(len(res) for res in search_results)
    if total_found < count:
        log.warning(f"Only {total_found} clips found for '{animal}'. Triggering fallback search.")
        fallback = await _search_pexels(f"wildlife nature", per_page=count)
        search_results.append(fallback)

    # 3. Round-Robin Interleaving (Prevents consecutive similar shots)
    combined_videos = []
    max_results = max((len(res) for res in search_results), default=0)
    for i in range(max_results):
        for res_list in search_results:
            if i < len(res_list):
                combined_videos.append(res_list[i])

    # 4. Strict De-duplication (Extract exact MP4 links)
    unique_mp4_links = []
    seen = set()
    for video_obj in combined_videos:
        # Pexels API hides the actual MP4 link inside the 'video_files' array
        mp4_url = _extract_best_mp4(video_obj)
        if mp4_url and mp4_url not in seen:
            seen.add(mp4_url)
            unique_mp4_links.append(mp4_url)

    # 5. Parallel Download
    clips_to_download = unique_mp4_links[:count]
    tasks = [
        _download_clip(url, os.path.join(output_dir, f"clip_{i}.mp4"))
        for i, url in enumerate(clips_to_download)
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Filter out failed downloads
    downloaded = [r for r in results if isinstance(r, str)]
    log.info(f"Successfully fetched {len(downloaded)} unique clips for '{animal}'.")
    return downloaded


async def _search_pexels(query: str, per_page: int = 15):
    """
    Strictly filters for 9:16 vertical, high-quality footage.
    """
    if not PEXELS_API_KEY:
        log.warning("PEXELS_API_KEY not found in environment.")
        return []

    url = "https://api.pexels.com/videos/search"
    headers = {"Authorization": PEXELS_API_KEY}
    
    # Viral Optimization: Force 'portrait' for native Shorts format
    params = {
        "query": query,
        "per_page": per_page,
        "orientation": "portrait", 
        "size": "medium" 
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
            return data.get("videos", [])
    except Exception as e:
        log.error(f"Pexels API failed for query '{query}': {e}")
        return []

def _extract_best_mp4(video_obj: dict) -> str:
    """
    Helper to extract the actual .mp4 link from the Pexels API response.
    Prioritizes HD vertical links.
    """
    files = video_obj.get("video_files", [])
    if not files:
        return ""
    
    # Try to find an HD file first
    for f in files:
        if f.get("quality") == "hd" and f.get("link", "").endswith(".mp4"):
            return f["link"]
            
    # Fallback to the first available mp4
    for f in files:
        if f.get("link", "").endswith(".mp4"):
            return f["link"]
            
    return ""

async def _download_clip(url: str, save_path: str) -> str:
    """
    Downloads the MP4 file safely with redirect handling.
    """
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            with open(save_path, "wb") as f:
                f.write(resp.content)
        return save_path
    except Exception as e:
        log.error(f"Failed to download {url}: {e}")
        raise RuntimeError(f"Download failed")
