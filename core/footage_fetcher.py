import os, asyncio, logging, httpx, random
from pathlib import Path

log = logging.getLogger(__name__)
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")

async def fetch_footage(animal: str, count: int = 12, output_dir: str = "output/footage") -> list[str]:
    """
    UPGRADED: Fetches 9:16 vertical footage with multi-layered search intent.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # 1. Define tiered search queries for maximum variety
    # Viral shorts thrive on 'The subject' + 'The habitat' + 'The action'
    queries = [
        f"{animal}",                          # Primary subject
        f"{animal} close up",                 # High-detail (retention)
        f"{animal} wild nature",              # Habitat B-roll
    ]
    
    # Add aggressive modifier for predators
    if any(p in animal.lower() for p in ["lion", "shark", "wolf", "predator", "eagle"]):
        queries.append(f"{animal} attack hunt")
    else:
        queries.append(f"{animal} funny cute")

    # 2. Execute searches in parallel
    search_tasks = [_search_pexels(q, per_page=10) for q in queries]
    search_results = await asyncio.gather(*search_tasks)
    
    # 3. Interleave results to ensure no two consecutive clips look the same
    combined_videos = []
    for i in range(10):  # Round-robin through the different query results
        for res_list in search_results:
            if i < len(res_list):
                combined_videos.append(res_list[i])

    # 4. De-duplicate and filter
    unique_videos = []
    seen = set()
    for v in combined_videos:
        if v["url"] not in seen:
            seen.add(v["url"])
            unique_videos.append(v)

    # 5. Parallel download
    clips_to_download = unique_videos[:count]
    tasks = [
        _download_clip(video["url"], os.path.join(output_dir, f"clip_{i}.mp4"))
        for i, video in enumerate(clips_to_download)
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    downloaded = [r for r in results if isinstance(r, str)]
    
    log.info(f"Fetched {len(downloaded)} unique clips for '{animal}' using tiered search.")
    return downloaded

async def _search_pexels(query: str, per_page: int = 15):
    """
    UPGRADED: Added strict vertical orientation and size filtering.
    """
    if not PEXELS_API_KEY:
        log.warning("PEXELS_API_KEY not found.")
        return []

    url = "https://api.pexels.com/videos/search"
    headers = {"Authorization": PEXELS_API_KEY}
    # Viral Optimization: size='medium' and orientation='portrait' ensure 9:16 HD
    params = {
        "query": query,
        "per_page": per_page,
        "orientation": "portrait",
        "size": "medium" 
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
            return data.get("videos", [])
    except Exception as e:
        log.error(f"Pexels search failed for '{query}': {e}")
        return []

# ... [_download_clip remains same]
