"""
Footage Fetcher — downloads free HD animal footage from Pexels.
VIRAL UPDATE: Contextual Dual-Search to provide visual variety (Animal + Action).
"""
import os, asyncio, logging, httpx
from pathlib import Path

log = logging.getLogger(__name__)
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")

async def fetch_footage(animal: str, count: int = 10, output_dir: str = "output/footage") -> list[str]:
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # 1. Search the specific animal
    primary_videos = await _search_pexels(animal, per_page=15)
    
    # 2. Search a contextual/action modifier to mix up the b-roll
    action_modifier = f"{animal} attack" if "predator" in animal.lower() else f"{animal} wild nature"
    secondary_videos = await _search_pexels(action_modifier, per_page=10)

    # Combine them interchangeably (Clip 1 = Primary, Clip 2 = Secondary, etc.)
    combined_videos = []
    max_len = max(len(primary_videos), len(secondary_videos))
    for i in range(max_len):
        if i < len(primary_videos): combined_videos.append(primary_videos[i])
        if i < len(secondary_videos): combined_videos.append(secondary_videos[i])

    # De-duplicate
    unique_videos = []
    seen = set()
    for v in combined_videos:
        if v["url"] not in seen:
            seen.add(v["url"])
            unique_videos.append(v)

    clips_to_download = unique_videos[:count]
    tasks = [
        _download_clip(video["url"], os.path.join(output_dir, f"clip_{i}.mp4"))
        for i, video in enumerate(clips_to_download)
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in results if isinstance(r, str)]

# ... [Keep existing _search_pexels and _download_clip functions] ...
