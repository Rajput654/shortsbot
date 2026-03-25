"""
Trending Audio Manager v3.1

FIXES v3.1:
- DEAD CDN URL: The Pixabay CDN URL (cdn.pixabay.com/download/...) returns
  HTTP 403 Forbidden in CI environments (GitHub Actions, Railway). Replaced
  with a multi-source fallback chain:
    1. Free Music Archive (CC0, direct MP3 links, CI-accessible)
    2. A committed fallback file in assets/music/ (most reliable — see note)
    3. Silent fallback with a warning (videos still work, just no music)

BEST PRACTICE: Commit 1-2 royalty-free MP3 files directly into assets/music/
in your GitHub repo. That's the only 100% reliable approach — no external
dependency that can return 403 or change URLs. Sources:
  - YouTube Audio Library: https://www.youtube.com/audiolibrary (free, no attr)
  - Free Music Archive: https://freemusicarchive.org (filter CC0)
  - Pixabay Music: https://pixabay.com/music/ (CC0, download manually first)

UPGRADES v3.0 (retained):
- AUTO-DOWNLOAD DEFAULT TRACK at startup if music dir is empty.
- VOLUME: music is at 0.04 (set in video_assembler.py).
- MOOD-BASED TRACK SELECTION: matches track energy to script tone.
"""

import os, logging, random
from pathlib import Path

log = logging.getLogger(__name__)

MUSIC_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "music")

# FIX v3.1: Multiple fallback URLs in order of reliability.
# All are CC0 / no-attribution-required tracks.
# The bot tries each in sequence until one downloads successfully.
_FALLBACK_URLS = [
    # Free Music Archive — Jahzzar "Smile" (CC0)
    (
        "https://files.freemusicarchive.org/storage-freemusicarchive-org/"
        "music/no_curator/Jahzzar/Travellers_Guide/Jahzzar_-_05_-_Smile.mp3",
        "default_ambient.mp3",
    ),
    # Free Music Archive — Kevin MacLeod "Straight" (CC0 via FMA)
    (
        "https://files.freemusicarchive.org/storage-freemusicarchive-org/"
        "music/ccCommunity/Kevin_MacLeod/Jazz_Sampler/Kevin_MacLeod_-_Straight.mp3",
        "default_ambient.mp3",
    ),
]

DEFAULT_TRACK_FILENAME = "default_ambient.mp3"

TRENDING_TRACKS = [
    {
        "filename": "epic_drums.mp3",
        "energy":   "high",
        "mood":     ["battle", "fight", "strength", "fast", "destroy", "powerful"],
        "source":   "YouTube Audio Library",
    },
    {
        "filename": "suspense_build.mp3",
        "energy":   "high",
        "mood":     ["dark", "deep sea", "scary", "nightmare", "predator", "danger"],
        "source":   "YouTube Audio Library",
    },
    {
        "filename": "mystery_ambient.mp3",
        "energy":   "medium",
        "mood":     ["mystery", "smart", "brain", "impossible", "science", "explain"],
        "source":   "Pixabay",
    },
    {
        "filename": "upbeat_discovery.mp3",
        "energy":   "medium",
        "mood":     ["record", "extreme", "amazing", "survive", "superpower", "ability"],
        "source":   "YouTube Audio Library",
    },
    {
        "filename": "lo_fi_wonder.mp3",
        "energy":   "low",
        "mood":     ["cute", "baby", "tiny", "small", "surprising", "smart"],
        "source":   "Pixabay",
    },
    {
        "filename": DEFAULT_TRACK_FILENAME,
        "energy":   "medium",
        "mood":     ["ambient", "nature", "wildlife"],
        "source":   "Free Music Archive CC0 (auto-downloaded)",
    },
]


def ensure_default_track():
    """
    Download the default ambient track if no music files exist in assets/music/.
    Called at bot startup so the pipeline never runs silent.

    FIX v3.1: Tries multiple fallback URLs instead of a single Pixabay CDN
    link that returns 403 in CI. If all URLs fail, logs a clear warning and
    continues — videos still work without music.
    """
    Path(MUSIC_DIR).mkdir(parents=True, exist_ok=True)

    existing = [f for f in os.listdir(MUSIC_DIR) if f.endswith((".mp3", ".wav", ".ogg"))]
    if existing:
        return  # Already have music — nothing to do

    default_path = os.path.join(MUSIC_DIR, DEFAULT_TRACK_FILENAME)
    if os.path.exists(default_path):
        return  # Already downloaded

    log.info("No music found in assets/music/ — attempting to download default CC0 track...")

    import urllib.request
    import urllib.error

    for url, filename in _FALLBACK_URLS:
        save_path = os.path.join(MUSIC_DIR, filename)
        try:
            log.info(f"Trying: {url[:60]}...")
            urllib.request.urlretrieve(url, save_path)
            size_kb = os.path.getsize(save_path) // 1024
            if size_kb < 10:
                # Downloaded something suspiciously tiny — likely an error page
                os.remove(save_path)
                log.warning(f"Downloaded file too small ({size_kb} KB) — skipping")
                continue
            log.info(f"Default track downloaded: {filename} ({size_kb} KB)")
            return
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            log.warning(f"Download failed ({e}) — trying next URL")
            if os.path.exists(save_path):
                os.remove(save_path)

    log.warning(
        "All default track download attempts failed.\n"
        "Videos will run without background music.\n"
        "FIX: Commit an MP3 file directly into assets/music/ in your GitHub repo.\n"
        "     Sources: YouTube Audio Library, Free Music Archive (CC0), Pixabay Music."
    )


def get_track_for_script(script: dict) -> str | None:
    """Pick the best matching audio track for a script."""
    ensure_default_track()

    if not os.path.isdir(MUSIC_DIR):
        return None

    energy = _detect_script_energy(script)
    title  = (script.get("title", "") + " " + script.get("hook", "")).lower()

    available = []
    for track in TRENDING_TRACKS:
        path = os.path.join(MUSIC_DIR, track["filename"])
        if os.path.exists(path):
            available.append((track, path))

    for fname in os.listdir(MUSIC_DIR):
        if fname.endswith((".mp3", ".wav", ".ogg")):
            if not any(t["filename"] == fname for t, _ in available):
                available.append(({"energy": "medium", "mood": []}, os.path.join(MUSIC_DIR, fname)))

    if not available:
        return None

    best_track = None
    best_score = -1

    for track_meta, track_path in available:
        score = 10 if track_meta.get("energy") == energy else 0
        for mood_word in track_meta.get("mood", []):
            if mood_word in title:
                score += 3
        if score > best_score:
            best_score = score
            best_track = track_path

    if best_score < 3:
        _, best_track = random.choice(available)
        log.info(f"Random track selected: {os.path.basename(best_track)}")
    else:
        log.info(f"Track selected: {os.path.basename(best_track)} (score: {best_score}, energy: {energy})")

    return best_track


def _detect_script_energy(script: dict) -> str:
    combined = f"{script.get('shock_word','')} {script.get('title','')} {script.get('hook','')}".lower()
    high = [
        "destroy", "kill", "fight", "battle", "attack", "predator", "dangerous",
        "deadly", "terrifying", "insane", "strongest", "fastest", "biggest", "brutal", "extreme",
    ]
    low = ["cute", "baby", "tiny", "small", "smart", "clever", "gentle", "calm", "surprising"]
    if sum(1 for w in high if w in combined) >= 2:
        return "high"
    if sum(1 for w in low  if w in combined) >= 2:
        return "low"
    return "medium"
