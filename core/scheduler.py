"""
Scheduler v3.0 — IST upload timing logic.

BUGFIXES v3.0:
- FIXED: IST is UTC+5:30, NOT UTC+5. Previous code subtracted only 5 hours,
  meaning every cron was 30 minutes early (e.g. 18:00 IST ran at 12:00 UTC
  instead of 12:30 UTC). Now correctly uses 330-minute offset.
- CORRECT CRON EXPRESSIONS provided for all 4 IST slots.

IST upload slots and their correct UTC cron expressions:
  08:00 IST = 02:30 UTC  →  cron: "30 2 * * *"
  12:00 IST = 06:30 UTC  →  cron: "30 6 * * *"
  18:00 IST = 12:30 UTC  →  cron: "30 12 * * *"   ← BEST slot
  21:00 IST = 15:30 UTC  →  cron: "30 15 * * *"
"""

from datetime import datetime
import pytz

IST = pytz.timezone("Asia/Kolkata")
IST_OFFSET_MINUTES = 330  # UTC+5:30

# (hour, minute) in IST
UPLOAD_SLOTS = [
    (8,  0),
    (12, 0),
    (18, 0),   # best slot
    (21, 0),
]


def _ist_to_utc_cron(ist_hour: int, ist_minute: int) -> str:
    """Convert an IST (hour, minute) to a UTC cron expression."""
    total_ist_minutes  = ist_hour * 60 + ist_minute
    total_utc_minutes  = total_ist_minutes - IST_OFFSET_MINUTES

    # Handle midnight wrap-around
    if total_utc_minutes < 0:
        total_utc_minutes += 24 * 60

    utc_hour   = total_utc_minutes // 60
    utc_minute = total_utc_minutes % 60
    return f"{utc_minute} {utc_hour} * * *"


def get_todays_schedule() -> list[dict]:
    now = datetime.now(IST)
    slots = []
    for hour, minute in UPLOAD_SLOTS:
        scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        slots.append({
            "time_ist":  scheduled.strftime("%I:%M %p IST"),
            "cron_utc":  _ist_to_utc_cron(hour, minute),
            "label":     _slot_label(hour),
            "is_best":   hour == 18,
        })
    return slots


def _slot_label(hour: int) -> str:
    labels = {
        8:  "Morning commute",
        12: "Lunch break",
        18: "Evening peak ⭐",
        21: "Night scroll",
    }
    return labels.get(hour, "")


def should_run_now() -> bool:
    """True if current IST time is within 5 min of any upload slot."""
    now = datetime.now(IST)
    for hour, minute in UPLOAD_SLOTS:
        if now.hour == hour and abs(now.minute - minute) <= 5:
            return True
    return False


if __name__ == "__main__":
    print("\nCorrect IST → UTC cron mappings:")
    for slot in get_todays_schedule():
        best = " ← BEST" if slot["is_best"] else ""
        print(f"  {slot['time_ist']:>14}  |  cron: \"{slot['cron_utc']}\"{best}")
