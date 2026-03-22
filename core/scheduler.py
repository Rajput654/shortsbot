"""
Scheduler — determines best upload times for Indian audience (IST).
Used by cron job / Railway cron to trigger pipeline at right time.
"""

from datetime import datetime
import pytz

IST = pytz.timezone("Asia/Kolkata")

# Best upload times in IST (Hour, Minute)
UPLOAD_SLOTS = [
    (8, 0),   # Morning commute — high engagement
    (12, 0),  # Lunch break
    (18, 0),  # Evening peak — BEST slot
    (21, 0),  # Night scroll
]

def get_todays_schedule() -> list[dict]:
    now = datetime.now(IST)
    slots = []
    for hour, minute in UPLOAD_SLOTS:
        scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        slots.append({
            "time_ist": scheduled.strftime("%I:%M %p IST"),
            "cron_utc": f"{minute} {hour - 5} * * *",  # IST = UTC+5:30
            "label": _slot_label(hour),
            "is_best": hour == 18,
        })
    return slots

def _slot_label(hour: int) -> str:
    labels = {8: "Morning commute", 12: "Lunch break", 18: "Evening peak ⭐", 21: "Night scroll"}
    return labels.get(hour, "")

def should_run_now() -> bool:
    """Check if current IST time matches any upload slot (within 5 min window)."""
    now = datetime.now(IST)
    for hour, minute in UPLOAD_SLOTS:
        if now.hour == hour and abs(now.minute - minute) <= 5:
            return True
    return False
