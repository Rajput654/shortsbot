"""
Animal Tracker — keeps track of which animals have been used.
Saves to a simple JSON file so it persists across runs forever.
Never repeats the same animal until all animals are exhausted,
then resets and starts fresh.
"""

import os, json, logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

TRACKER_FILE = os.path.join(os.path.dirname(__file__), "..", "used_animals.json")


def _load() -> dict:
    """Load tracker data from file."""
    if os.path.exists(TRACKER_FILE):
        try:
            with open(TRACKER_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"used": [], "history": []}


def _save(data: dict):
    """Save tracker data to file."""
    with open(TRACKER_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_used_animals() -> list[str]:
    """Return list of all animals already used."""
    return _load().get("used", [])


def mark_animals_used(animals: list[str]):
    """Mark animals as used after videos are generated."""
    data = _load()
    used = data.get("used", [])
    history = data.get("history", [])

    for animal in animals:
        animal_lower = animal.lower().strip()
        if animal_lower not in used:
            used.append(animal_lower)
            history.append({
                "animal": animal_lower,
                "date": datetime.now().strftime("%Y-%m-%d %H:%M")
            })
            log.info(f"Marked as used: {animal_lower}")

    data["used"] = used
    data["history"] = history
    _save(data)
    log.info(f"Total unique animals used so far: {len(used)}")


def reset_tracker():
    """Reset tracker — call this manually if you want to start fresh."""
    data = _load()
    old_count = len(data.get("used", []))
    data["used"] = []
    data["history"] = []
    _save(data)
    log.info(f"Tracker reset — cleared {old_count} animals")


def get_stats() -> dict:
    """Get tracker statistics."""
    data = _load()
    used = data.get("used", [])
    history = data.get("history", [])
    return {
        "total_used": len(used),
        "all_animals": used,
        "last_10": history[-10:] if history else []
    }


def build_exclusion_prompt(used_animals: list[str]) -> str:
    """Build a prompt instruction to exclude already-used animals."""
    if not used_animals:
        return ""
    # Only show last 50 to keep prompt manageable
    recent = used_animals[-50:]
    animals_str = ", ".join(recent)
    return (
        f"\n\nCRITICAL — DO NOT use any of these animals (already made videos about them): "
        f"{animals_str}\n"
        f"You MUST pick completely different animals not in this list."
    )
