"""
Animal Tracker — keeps track of which animals have been used.
SAVES to used_animals.json to persist across runs.

UPDATES v2:
- FUZZY NORMALIZATION: Automatically strips 's' from plurals and removes 
  extra spaces/casing to prevent "Lion" and "Lions" being treated as different.
- ATOMIC SAVING: Prevents file corruption if the bot crashes during a write.
- EXTENDED HISTORY: Maintains a timestamped log of every animal ever used.
"""

import os, json, logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

#
TRACKER_FILE = os.path.join(os.path.dirname(__file__), "..", "used_animals.json")

def _normalize(animal: str) -> str:
    """Normalize animal names to prevent duplicates like 'Lion' and 'Lions'."""
    name = animal.lower().strip()
    # Basic plural stripping for common cases
    if name.endswith('s') and len(name) > 4:
        # e.g., 'lions' -> 'lion', but not 'bass' -> 'bas'
        name = name[:-1]
    return name

def _load() -> dict:
    """Load tracker data from file."""
    if os.path.exists(TRACKER_FILE):
        try:
            with open(TRACKER_FILE, "r") as f:
                data = json.load(f)
                # Ensure structure exists even if file was manualy edited
                if "used" not in data: data["used"] = []
                if "history" not in data: data["history"] = []
                return data
        except Exception as e:
            log.warning(f"Tracker load failed: {e}. Starting fresh.")
    return {"used": [], "history": []}

def _save(data: dict):
    """Save tracker data to file atomically."""
    temp_file = f"{TRACKER_FILE}.tmp"
    try:
        with open(temp_file, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_file, TRACKER_FILE) # Atomic swap
    except Exception as e:
        log.error(f"Failed to save tracker: {e}")

def get_used_animals() -> list[str]:
    """Return list of all animals already used."""
    return _load().get("used", [])

def mark_animals_used(animals: list[str]):
    """Mark animals as used and record the timestamp."""
    data = _load()
    used = set(data.get("used", [])) # Use set for faster lookup
    history = data.get("history", [])

    for animal in animals:
        clean_name = _normalize(animal)
        if clean_name not in used:
            used.add(clean_name)
            history.append({
                "animal": clean_name,
                "date": datetime.now().strftime("%Y-%m-%d %H:%M")
            })
            log.info(f"✅ Registered new animal: {clean_name}")

    data["used"] = sorted(list(used))
    data["history"] = history
    _save(data)
    log.info(f"Total unique animals in database: {len(used)}")

def build_exclusion_prompt(used_animals: list[str]) -> str:
    """Build the instruction for the AI to ignore used topics."""
    if not used_animals:
        return ""
    
    # viral update: prioritize most recent 100 to keep the AI from repeating 
    # its own recent 'favorite' patterns.
    recent = used_animals[-100:]
    animals_str = ", ".join(recent)
    
    return (
        f"\nCRITICAL: DO NOT use any of these animals: {animals_str}.\n"
        f"Pick a completely different animal not mentioned above."
    )
