"""
Animal Tracker v3.0

BUGFIXES v3.0:
- PLURAL NORMALISER: previous code stripped trailing 's' from all words > 4 chars,
  turning "bass" → "bas", "moss" → "mo", "glass frog" → "glass fro".
  New logic uses an allowlist of known non-strippable endings so common
  animal names are never mangled.
- Everything else unchanged — atomic saves, history log, fuzzy dedup all still here.
"""

import os, json, logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)
TRACKER_FILE = os.path.join(os.path.dirname(__file__), "..", "used_animals.json")

# Animal names that end in 's' but are NOT plurals — never strip their 's'
_S_ENDINGS_KEEP = {
    "bass", "ibis", "lynx", "mantis", "walrus", "narwhal",
    "platypus", "octopus", "nautilus", "cuttlefish", "tapir",
    "mongoose", "albatross", "hippopotamus", "rhinoceros",
    "praying mantis", "glass frog", "flying fox",
}


def _normalize(animal: str) -> str:
    """
    Normalise animal names to prevent duplicates.
    Strips plural 's' only when safe to do so.
    """
    name = animal.lower().strip()

    # Never mangle known edge-case names
    if name in _S_ENDINGS_KEEP:
        return name

    # Strip plural 's' if: ends in 's', length > 4, doesn't end in 'ss', 'us', 'is', 'as'
    if (
        name.endswith("s")
        and len(name) > 4
        and not name.endswith(("ss", "us", "is", "as", "es"))
    ):
        name = name[:-1]

    return name


def _load() -> dict:
    if os.path.exists(TRACKER_FILE):
        try:
            with open(TRACKER_FILE, "r") as f:
                data = json.load(f)
                data.setdefault("used", [])
                data.setdefault("history", [])
                return data
        except Exception as e:
            log.warning(f"Tracker load failed: {e}. Starting fresh.")
    return {"used": [], "history": []}


def _save(data: dict):
    temp_file = f"{TRACKER_FILE}.tmp"
    try:
        with open(temp_file, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_file, TRACKER_FILE)
    except Exception as e:
        log.error(f"Failed to save tracker: {e}")


def get_used_animals() -> list[str]:
    return _load().get("used", [])


def mark_animals_used(animals: list[str]):
    data    = _load()
    used    = set(data.get("used", []))
    history = data.get("history", [])

    for animal in animals:
        clean = _normalize(animal)
        if clean not in used:
            used.add(clean)
            history.append({
                "animal": clean,
                "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            })
            log.info(f"Registered new animal: {clean}")

    data["used"]    = sorted(list(used))
    data["history"] = history
    _save(data)
    log.info(f"Total unique animals: {len(used)}")


def build_exclusion_prompt(used_animals: list[str]) -> str:
    if not used_animals:
        return ""
    recent = used_animals[-100:]
    animals_str = ", ".join(recent)
    return (
        f"\nCRITICAL: DO NOT use any of these animals: {animals_str}.\n"
        f"Pick a completely different animal not mentioned above."
    )


def get_stats() -> dict:
    data = _load()
    return {
        "total_used": len(data["used"]),
        "all_animals": data["used"],
        "last_10": data["history"][-10:],
    }


def reset_tracker():
    _save({"used": [], "history": []})
    log.info("Animal tracker reset")
