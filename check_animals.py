"""
check_animals.py — Run this anytime to see which animals have been used.
Usage: python check_animals.py
       python check_animals.py --reset   (start fresh)
"""

import sys, os
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, os.path.dirname(__file__))
from core.animal_tracker import get_stats, reset_tracker

if "--reset" in sys.argv:
    confirm = input("Are you sure you want to reset all animal tracking? (yes/no): ")
    if confirm.lower() == "yes":
        reset_tracker()
        print("✅ Tracker reset — all animals cleared")
    else:
        print("❌ Reset cancelled")
    sys.exit()

stats = get_stats()
print("\n" + "="*50)
print(f"🐾 ANIMAL TRACKER REPORT")
print("="*50)
print(f"Total unique animals used: {stats['total_used']}")
print("\nAll animals used (alphabetical):")
for i, animal in enumerate(sorted(stats['all_animals']), 1):
    print(f"  {i:3}. {animal}")

print("\nLast 10 videos made:")
for entry in stats['last_10']:
    print(f"  [{entry['date']}] {entry['animal']}")
print("="*50 + "\n")
