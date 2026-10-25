"""Loader for the generated briefing evaluation scenarios."""

import json
from pathlib import Path

SCENARIO_DIR = Path(__file__).resolve().parent / "scenarios"
EXPECTED_CATEGORY_COUNTS = {
    "normal_trip": 8,
    "severe_or_no_travel": 5,
    "forecast_unavailable": 5,
    "threshold_boundary": 4,
    "all_routes_risky": 3,
    "near_tie_routes": 3,
}


def load_scenarios():
    """Load the checked-in golden scenarios in a stable order."""
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(SCENARIO_DIR.glob("*.golden.json"))
    ]
