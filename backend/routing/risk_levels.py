"""Canonical ordered checkpoint risk levels."""

RISK_LEVELS = ["Low", "Moderate", "High", "Severe", "No Travel"]
LOW, MODERATE, HIGH, SEVERE, NO_TRAVEL = RISK_LEVELS
RISK_SCORES = {level: score for score, level in enumerate(RISK_LEVELS)}
