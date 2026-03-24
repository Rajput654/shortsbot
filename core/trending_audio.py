"""
Trending Audio Manager — manages a curated list of trending-style audio tracks.

WHY THIS MATTERS:
YouTube actively boosts Shorts using trending audio. Creators using trending
sounds get pushed to existing fans of that sound, giving a free second
distribution channel. This module manages a manually-curated trending list
and auto-selects the best track for each video's energy level.

HOW TO USE:
1. Download trending-style tracks from YouTube Audio Library:
   https://www.youtube.com/audiolibrary
   Filter: "No attribution required" + sort by "Most popular"

2. Also download from Pixabay Music (free, no attribution):
   https://pixabay.com/music/

3. Save tracks to assets/music/ with descriptive names:
   - assets/music/epic_drums_trending.mp3
   - assets/music/suspense_build.mp3
   - assets/music/lo_fi_chill.mp3

4. Update TRENDING_TRACKS below with metadata for each file.
   Set "energy" to match the subniche energy:
   - "high" = fight/battle/record videos
   - "medium" = mystery/smart animal videos
   - "low" = cute/surprising animal videos

The module will auto-match track energy to script energy based on
shock_word and subniche type.
"""

import os, random, logging
from pathlib import Path

log = logging.getLogger(__name__)

MUSIC_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "music")

# ── Curated trending track metadata ───────────────────────────────────────────
# Update this list as you add/remove tracks from assets/music/
# energy: "high" | "medium" | "low"
# mood: tags to match against script content
TRENDING_TRACKS = [
    {
        "filename": "epic_drums.mp3",
        "energy": "high",
        "mood": ["battle", "fight", "strength", "fast", "destroy", "powerful"],
        "source": "YouTube Audio Library"
    },
    {
        "filename": "suspense_build.mp3",
        "energy": "high",
        "mood": ["dark", "deep sea", "scary", "nightmare", "predator", "danger"],
        "source": "YouTube Audio Library"
    },
    {
        "filename": "mystery_ambient.mp3",
        "energy": "medium",
        "mood": ["mystery", "smart", "brain", "impossible", "science", "explain"],
        "source": "Pixabay"
    },
    {
        "filename": "upbeat_discovery.mp3",
        "energy": "medium",
        "mood": ["record", "extreme", "amazing", "survive", "superpower", "ability"],
        "source": "YouTube Audio Library"
    },
    {
        "filename": "lo_fi_wonder.mp3",
        "energy": "low",
        "mood": ["cute", "baby", "tiny", "small", "surprising", "smart"],
        "source": "Pixabay"
    },
]


def get_track_for_script(script: dict) -> str | None:
    """
    Pick the best matching audio track for a given script.
    Matches on energy level derived from shock_word and title keywords.
    Falls back to random available track if no match.
    """
    if not os.path.isdir(MUSIC_DIR):
        log.warning(f"Music dir not found: {MUSIC_DIR}")
        return None

    # Determine energy level from script
    energy = _detect_script_energy(script)
    title = (script.get("title", "") + " " + script.get("hook", "")).lower()

    # Find all tracks that exist on disk
    available = []
    for track in TRENDING_TRACKS:
        path = os.path.join(MUSIC_DIR, track["filename"])
        if os.path.exists(path):
            available.append((track, path))

    # Also scan for any mp3/wav files not in the curated list
    for fname in os.listdir(MUSIC_DIR):
        if fname.endswith((".mp3", ".wav", ".ogg")):
            if not any(t["filename"] == fname for t, _ in available):
                available.append(({"energy": "medium", "mood": []}, os.path.join(MUSIC_DIR, fname)))

    if not available:
        log.warning("No audio tracks found in assets/music/ — running without music")
        return None

    # Score each available track
    best_track = None
    best_score = -1

    for track_meta, track_path in available:
        score = 0

        # Energy match
        if track_meta.get("energy") == energy:
            score += 10

        # Mood keyword match
        for mood_word in track_meta.get("mood", []):
            if mood_word in title:
                score += 3

        if score > best_score:
            best_score = score
            best_track = track_path

    # If no good match, pick random
    if best_score < 3:
        _, best_track = random.choice(available)
        log.info(f"No strong track match — using random: {os.path.basename(best_track)}")
    else:
        log.info(f"Selected track: {os.path.basename(best_track)} (score: {best_score}, energy: {energy})")

    return best_track


def _detect_script_energy(script: dict) -> str:
    """Detect whether a script needs high/medium/low energy music."""
    shock_word = script.get("shock_word", "").lower()
    title = script.get("title", "").lower()
    hook = script.get("hook", "").lower()
    combined = f"{shock_word} {title} {hook}"

    high_energy_words = [
        "destroy", "kill", "fight", "battle", "punch", "attack", "predator",
        "dangerous", "deadly", "terrifying", "insane", "wild", "impossible",
        "strongest", "fastest", "biggest", "brutal", "epic", "extreme"
    ]

    low_energy_words = [
        "cute", "baby", "tiny", "small", "smart", "clever", "gentle",
        "calm", "peaceful", "surprising", "interesting", "weird", "odd"
    ]

    high_count = sum(1 for w in high_energy_words if w in combined)
    low_count = sum(1 for w in low_energy_words if w in combined)

    if high_count >= 2:
        return "high"
    elif low_count >= 2:
        return "low"
    else:
        return "medium"


def list_available_tracks() -> list[dict]:
    """List all audio tracks currently available in assets/music/."""
    if not os.path.isdir(MUSIC_DIR):
        return []

    tracks = []
    for fname in os.listdir(MUSIC_DIR):
        if fname.endswith((".mp3", ".wav", ".ogg")):
            path = os.path.join(MUSIC_DIR, fname)
            size_kb = os.path.getsize(path) // 1024
            meta = next((t for t in TRENDING_TRACKS if t["filename"] == fname), {})
            tracks.append({
                "filename": fname,
                "size_kb": size_kb,
                "energy": meta.get("energy", "unknown"),
                "source": meta.get("source", "unknown")
            })
    return tracks


def print_setup_instructions():
    """Print instructions for adding trending audio tracks."""
    print("""
╔══════════════════════════════════════════════════════╗
║           TRENDING AUDIO SETUP GUIDE                 ║
╠══════════════════════════════════════════════════════╣
║                                                      ║
║  1. YouTube Audio Library (free, no attribution)     ║
║     https://www.youtube.com/audiolibrary             ║
║     → Filter: "No attribution required"              ║
║     → Sort by: Most popular                          ║
║     → Download 5–10 tracks in different energy       ║
║                                                      ║
║  2. Pixabay Music (free, no attribution)             ║
║     https://pixabay.com/music/                       ║
║     → Filter: Trending / Most popular                ║
║     → Download 3–5 tracks                            ║
║                                                      ║
║  3. Save all tracks to: assets/music/                ║
║                                                      ║
║  4. Update TRENDING_TRACKS list in                   ║
║     core/trending_audio.py with filenames            ║
║     and energy levels                                ║
║                                                      ║
╚══════════════════════════════════════════════════════╝
""")


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    print_setup_instructions()
    tracks = list_available_tracks()
    if tracks:
        print(f"Found {len(tracks)} tracks:")
        for t in tracks:
            print(f"  {t['filename']} ({t['size_kb']} KB, energy: {t['energy']})")
    else:
        print("No tracks found in assets/music/ — add some!")
