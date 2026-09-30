"""Double-click to open Symptom Tracker (runs without a console window)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from symptom_tracker.app import main

main()
