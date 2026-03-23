"""
YouTube Channel Scanner — fetches ALL videos from your channel and extracts
animal keywords from their titles/descriptions.

Runs at the START of every pipeline run (before script generation) so the
animal tracker is always up-to-date with what's actually on the channel.

This prevents duplicates even if:
- used_animals.json was deleted or reset
- Videos were uploaded manually outside the bot
- The bot ran on a different machine

How it works:
1. Fetches all uploads from your channel using YouTube Data API v3
2. Extracts animal name from each video title using a keyword scan
3. Merges found animals into used_animals.json via the existing tracker
4. Caches the scan result so it only re-scans if the channel has new videos

Cost: ~3 quota units per 50 videos fetched (very cheap)
"""

import os, json, re, logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

CACHE_FILE = os.path.join(os.path.dirname(__file__), "..", "channel_scan_cache.json")

# Common English words to ignore when extracting animal names from titles
TITLE_STOPWORDS = {
    "the", "a", "an", "this", "that", "is", "are", "was", "were", "can", "will",
    "would", "could", "should", "has", "have", "had", "does", "do", "did",
    "its", "it", "and", "or", "but", "so", "yet", "for", "nor", "not",
    "with", "without", "from", "into", "onto", "upon", "about", "above",
    "below", "between", "through", "during", "before", "after", "against",
    "at", "by", "in", "of", "on", "to", "up", "as", "if", "then", "than",
    "when", "where", "which", "who", "how", "why", "what", "no", "yes",
    "vs", "vs.", "ever", "every", "never", "always", "only", "just",
    "still", "even", "most", "more", "less", "very", "too", "so", "such",
    "shorts", "animal", "animals", "facts", "fact", "wild", "nature",
    "world", "top", "best", "most", "amazing", "insane", "crazy", "weird",
    "you", "your", "we", "our", "they", "their", "he", "she", "my", "i",
    "wins", "loses", "beats", "killed", "kills", "survived", "watch",
    "seconds", "minutes", "hours", "days", "years", "pounds", "feet",
    "meet", "found", "discovered", "real", "actually", "literally",
    "shocking", "unbelievable", "impossible", "terrifying", "deadly",
    "dangerous", "powerful", "strongest", "fastest", "biggest", "smallest",
    "wait", "nope", "wild", "wow", "omg", "wtf", "lol"
}

# Well-known animals for smarter extraction
KNOWN_ANIMALS = {
    # Mammals
    "lion", "tiger", "cheetah", "leopard", "jaguar", "cougar", "puma",
    "elephant", "rhinoceros", "rhino", "hippopotamus", "hippo",
    "giraffe", "zebra", "wildebeest", "gnu", "bison", "buffalo",
    "wolf", "coyote", "fox", "dog", "cat", "bear", "grizzly", "polar bear",
    "panda", "koala", "kangaroo", "wallaby", "wombat", "platypus",
    "gorilla", "chimpanzee", "orangutan", "baboon", "monkey", "lemur",
    "dolphin", "whale", "orca", "killer whale", "blue whale", "sperm whale",
    "seal", "sea lion", "walrus", "otter", "beaver", "muskrat",
    "deer", "elk", "moose", "reindeer", "caribou", "antelope", "gazelle",
    "horse", "donkey", "zebra", "camel", "llama", "alpaca",
    "bat", "flying fox", "vampire bat",
    "mole", "shrew", "hedgehog", "porcupine", "skunk",
    "squirrel", "chipmunk", "groundhog", "prairie dog", "rat", "mouse",
    "rabbit", "hare", "jackrabbit",
    "opossum", "armadillo", "sloth", "anteater", "pangolin",
    "hyena", "aardvark", "meerkat", "mongoose", "badger", "wolverine",
    "weasel", "ferret", "mink", "stoat",
    "naked mole rat", "capybara", "tapir",
    # Birds
    "eagle", "hawk", "falcon", "osprey", "vulture", "condor",
    "owl", "heron", "crane", "stork", "pelican", "flamingo",
    "penguin", "albatross", "petrel", "puffin",
    "parrot", "macaw", "cockatoo", "toucan", "hornbill",
    "peacock", "pheasant", "turkey", "chicken", "duck", "goose", "swan",
    "ostrich", "emu", "cassowary", "kiwi",
    "hummingbird", "swift", "swallow", "kingfisher",
    "crow", "raven", "magpie", "jay",
    "pigeon", "dove", "roadrunner",
    # Reptiles
    "crocodile", "alligator", "caiman", "gharial",
    "komodo dragon", "monitor lizard", "iguana", "chameleon",
    "gecko", "skink", "gila monster",
    "python", "boa constrictor", "anaconda", "cobra", "mamba",
    "rattlesnake", "viper", "taipan", "sea snake",
    "tortoise", "turtle", "sea turtle", "snapping turtle",
    # Amphibians
    "frog", "toad", "tree frog", "bullfrog",
    "salamander", "axolotl", "mudpuppy",
    "caecilian",
    # Fish
    "shark", "great white", "bull shark", "hammerhead", "whale shark",
    "ray", "stingray", "manta ray",
    "tuna", "swordfish", "marlin", "sailfish",
    "piranha", "barracuda", "moray eel", "electric eel",
    "clownfish", "pufferfish", "anglerfish", "lanternfish",
    "salmon", "trout", "bass", "carp", "catfish",
    "seahorse", "lionfish", "stonefish",
    # Invertebrates / Marine
    "octopus", "squid", "cuttlefish", "nautilus",
    "jellyfish", "sea anemone", "coral",
    "lobster", "crab", "shrimp", "mantis shrimp",
    "spider", "tarantula", "black widow", "funnel web",
    "scorpion", "centipede", "millipede",
    "ant", "army ant", "fire ant", "leafcutter ant",
    "bee", "wasp", "hornet", "bumblebee",
    "beetle", "bombardier beetle", "dung beetle",
    "butterfly", "moth", "dragonfly", "praying mantis",
    "cockroach", "termite", "grasshopper", "locust",
    "tick", "mite", "flea",
    "starfish", "sea urchin", "sea cucumber",
    "worm", "earthworm", "leech",
    # Deep sea / Special
    "blobfish", "dumbo octopus", "giant squid", "vampire squid",
    "goblin shark", "frilled shark", "oarfish", "coelacanth",
    "tardigrade", "water bear",
}


def _get_youtube_client():
    """Build an authenticated YouTube API client."""
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

    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def _get_channel_uploads_playlist_id(youtube) -> str:
    """Get the 'uploads' playlist ID for the authenticated channel."""
    response = youtube.channels().list(
        part="contentDetails",
        mine=True
    ).execute()

    items = response.get("items", [])
    if not items:
        raise ValueError("No channel found for these credentials")

    playlist_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    log.info(f"Channel uploads playlist: {playlist_id}")
    return playlist_id


def _fetch_all_video_titles(youtube, playlist_id: str) -> list[dict]:
    """
    Page through the uploads playlist and collect all video titles + IDs.
    Each page costs 1 quota unit. 500 videos = ~10 units.
    """
    videos = []
    next_page_token = None

    while True:
        params = {
            "part": "snippet",
            "playlistId": playlist_id,
            "maxResults": 50,
        }
        if next_page_token:
            params["pageToken"] = next_page_token

        response = youtube.playlistItems().list(**params).execute()

        for item in response.get("items", []):
            snippet = item.get("snippet", {})
            title = snippet.get("title", "")
            video_id = snippet.get("resourceId", {}).get("videoId", "")
            description = snippet.get("description", "")
            published = snippet.get("publishedAt", "")

            if title and video_id:
                videos.append({
                    "video_id": video_id,
                    "title": title,
                    "description": description[:500],  # first 500 chars only
                    "published": published,
                })

        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break

        log.info(f"Fetched {len(videos)} videos so far...")

    log.info(f"Total videos on channel: {len(videos)}")
    return videos


def extract_animal_from_title(title: str, description: str = "") -> str | None:
    """
    Extract animal keyword from a video title/description.

    Strategy:
    1. Check against KNOWN_ANIMALS list (multi-word first, then single)
    2. Fall back to extracting nouns that aren't stopwords
    3. Returns None if no animal found
    """
    text = f"{title} {description}".lower()

    # Check multi-word animals first (e.g. "mantis shrimp", "naked mole rat")
    multi_word = sorted(
        [a for a in KNOWN_ANIMALS if " " in a],
        key=lambda x: len(x),
        reverse=True  # longest first to avoid partial matches
    )
    for animal in multi_word:
        if animal in text:
            return animal

    # Check single-word known animals
    words = re.findall(r'\b[a-z]+\b', text)
    for word in words:
        if word in KNOWN_ANIMALS:
            return word

    # Fallback: extract any non-stopword noun from the title only
    # (title is more reliable than description)
    title_words = re.findall(r'\b[a-z]+\b', title.lower())
    for word in title_words:
        if (
            len(word) >= 4 and
            word not in TITLE_STOPWORDS and
            word not in KNOWN_ANIMALS  # already checked above
        ):
            return word  # best guess

    return None


def _load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"video_count": 0, "last_scan": "", "found_animals": []}


def _save_cache(data: dict):
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def scan_channel_and_update_tracker(force: bool = False) -> list[str]:
    """
    Main entry point — scans the YouTube channel and updates used_animals.json.

    Args:
        force: If True, re-scans even if cache is fresh.

    Returns:
        List of animal names found on the channel.
    """
    from core.animal_tracker import mark_animals_used, get_used_animals

    log.info("🔍 Scanning YouTube channel for existing animal videos...")

    try:
        youtube = _get_youtube_client()
    except Exception as e:
        log.warning(f"Could not connect to YouTube API: {e} — skipping channel scan")
        return []

    try:
        playlist_id = _get_channel_uploads_playlist_id(youtube)
    except Exception as e:
        log.warning(f"Could not get uploads playlist: {e} — skipping channel scan")
        return []

    # Check cache — if video count hasn't changed, skip re-scan
    cache = _load_cache()
    try:
        # Quick count check: fetch just 1 item to get total count
        count_response = youtube.playlistItems().list(
            part="snippet",
            playlistId=playlist_id,
            maxResults=1
        ).execute()
        total_on_channel = count_response.get("pageInfo", {}).get("totalResults", 0)
    except Exception as e:
        log.warning(f"Could not check video count: {e}")
        total_on_channel = 0

    if not force and cache.get("video_count") == total_on_channel and total_on_channel > 0:
        log.info(
            f"Channel unchanged ({total_on_channel} videos) — using cached scan. "
            f"Found {len(cache.get('found_animals', []))} animals previously."
        )
        return cache.get("found_animals", [])

    log.info(f"Channel has {total_on_channel} videos — running full scan...")

    # Full scan
    try:
        videos = _fetch_all_video_titles(youtube, playlist_id)
    except Exception as e:
        log.warning(f"Video fetch failed: {e} — skipping scan")
        return []

    found_animals = []
    skipped = []

    for video in videos:
        animal = extract_animal_from_title(video["title"], video["description"])
        if animal:
            found_animals.append(animal)
            log.debug(f"  Found: '{animal}' from '{video['title']}'")
        else:
            skipped.append(video["title"])

    if skipped:
        log.info(f"Could not extract animal from {len(skipped)} titles: {skipped[:5]}")

    # Merge into tracker
    already_tracked = get_used_animals()
    new_animals = [a for a in found_animals if a not in already_tracked]

    if new_animals:
        mark_animals_used(new_animals)
        log.info(f"✅ Added {len(new_animals)} channel animals to tracker: {new_animals}")
    else:
        log.info("✅ All channel animals already in tracker — nothing new to add")

    # Save cache
    _save_cache({
        "video_count": total_on_channel,
        "last_scan": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "found_animals": found_animals,
        "videos_scanned": len(videos),
    })

    log.info(
        f"Channel scan complete: {len(videos)} videos scanned, "
        f"{len(found_animals)} animals found, {len(new_animals)} new to tracker"
    )
    return found_animals


def print_channel_animals():
    """CLI helper — print all animals found on the channel."""
    from dotenv import load_dotenv
    load_dotenv()

    animals = scan_channel_and_update_tracker(force=True)
    print(f"\n{'='*50}")
    print(f"Animals found on your YouTube channel: {len(animals)}")
    print("="*50)
    for i, a in enumerate(sorted(set(animals)), 1):
        print(f"  {i:3}. {a}")
    print("="*50)


if __name__ == "__main__":
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    print_channel_animals()
