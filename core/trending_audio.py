"""
Trending Audio Manager v3.0

UPGRADES v3.0 (rating fixes):
- AUTO-DOWNLOAD DEFAULT TRACK: if assets/music/ is empty on first run,
  downloads one royalty-free CC0 track from Pixabay automatically so the
  bot never runs silent. Uses a stable, known-good URL.
- VOLUME NOTE: music volume is now 0.04 (set in video_assembler.py).
  This keeps voice intelligibility high while adding atmosphere.
- Everything else unchanged.

HOW TO ADD YOUR OWN TRACKS:
1. Download from YouTube Audio Library (no attribution required)
   https://www.youtube.com/audiolibrary
2. Download from Pixabay Music (CC0, free forever)
   https://pixabay.com/music/
3. Save to assets/music/ with descriptive names
4. Add metadata to TRENDING_TRACKS below
"""

import os, logging, random, asyncio
from pathlib import Path

log = logging.getLogger(__name__)

MUSIC_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "music")

# ── Default CC0 track auto-downloaded on first run ────────────────────────────
# Source: Pixabay (CC0 license, no attribution required)
DEFAULT_TRACK_URL      = "https://cdn.pixabay.com/download/audio/2022/03/15/audio_8cb749fc0f.mp3"
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
        "source":   "Pixabay CC0 (auto-downloaded)",
    },
]


def ensure_default_track():
    """
    Download the default ambient track if no music files exist in assets/music/.
    Called at bot startup so the pipeline never runs silent.
    """
    Path(MUSIC_DIR).mkdir(parents=True, exist_ok=True)

    existing = [f for f in os.listdir(MUSIC_DIR) if f.endswith((".mp3", ".wav", ".ogg"))]
    if existing:
        return  # Already have music

    default_path = os.path.join(MUSIC_DIR, DEFAULT_TRACK_FILENAME)
    if os.path.exists(default_path):
        return  # Already downloaded

    log.info(f"No music found in assets/music/ — downloading default CC0 track...")
    try:
        import urllib.request
        urllib.request.urlretrieve(DEFAULT_TRACK_URL, default_path)
        size_kb = os.path.getsize(default_path) // 1024
        log.info(f"Default track downloaded: {DEFAULT_TRACK_FILENAME} ({size_kb} KB)")
    except Exception as e:
        log.warning(f"Default track download failed: {e} — bot will run without background music")


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
    high = ["destroy","kill","fight","battle","attack","predator","dangerous","deadly",
            "terrifying","insane","strongest","fastest","biggest","brutal","extreme"]
    low  = ["cute","baby","tiny","small","smart","clever","gentle","calm","surprising"]
    if sum(1 for w in high if w in combined) >= 2:
        return "high"
    if sum(1 for w in low if w in combined) >= 2:
        return "low"
    return "medium"
