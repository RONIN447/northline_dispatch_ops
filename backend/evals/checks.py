"""Shared deterministic validation checks for generated dispatch briefings."""

import re
from decimal import Decimal, InvalidOperation
from typing import List, Set

from briefing.schema import Briefing
from routing.risk_levels import HIGH, RISK_SCORES

_NUMBER_PATTERN = re.compile(r"(?<![A-Za-z-])\d[\d,]*(?:\.\d+)?")
_WEATHER_FIELDS = ("windMph", "rainInHr", "snowInHr")


def validate_briefing(briefing: Briefing, route_plan: dict) -> List[str]:
    """Return stable check identifiers for unsupported or unsafe briefing claims."""
    errors = []
    routes = route_plan["routes"]
    recommended_route_id = route_plan["recommendedRouteId"]
    route_ids = {route["id"] for route in routes}

    if (
        briefing.recommended_route_id != recommended_route_id
        or briefing.recommended_route_id not in route_ids
    ):
        errors.append("recommended_route_mismatch")

    expected_risks = set()
    expected_gaps = set()
    for route in routes:
        for index, checkpoint in enumerate(route["checkpoints"]):
            risk = checkpoint.get("risk")
            if risk in RISK_SCORES and RISK_SCORES[risk] >= RISK_SCORES[HIGH]:
                expected_risks.add((route["id"], index, risk))
            missing = [field for field in _WEATHER_FIELDS if checkpoint.get(field) is None]
            if missing:
                expected_gaps.add(
                    "{} checkpoint {} is missing {}.".format(
                        route["id"], index, ", ".join(missing)
                    )
                )

    actual_risks = {
        (item.route_id, item.checkpoint_index, item.level)
        for item in briefing.risky_checkpoints
    }
    if actual_risks != expected_risks or len(actual_risks) != len(briefing.risky_checkpoints):
        errors.append("risky_checkpoint_mismatch")
    if set(briefing.data_gaps) != expected_gaps or len(set(briefing.data_gaps)) != len(
        briefing.data_gaps
    ):
        errors.append("data_gap_mismatch")

    allowed_numbers = _route_plan_numbers(route_plan)
    claims = "{} {}".format(briefing.summary, " ".join(briefing.dispatcher_actions))
    for match in _NUMBER_PATTERN.finditer(claims):
        try:
            number = Decimal(match.group().replace(",", "")).normalize()
        except InvalidOperation:
            continue
        if number not in allowed_numbers:
            errors.append("unsupported_number")
            break
    return errors


def _route_plan_numbers(route_plan: dict) -> Set[Decimal]:
    numbers = {Decimal(str(len(route_plan["routes"]))).normalize()}
    for route in route_plan["routes"]:
        for field in (
            "distanceMiles",
            "durationHours",
            "severeMiles",
            "highMiles",
            "noTravelMiles",
            "averageRisk",
        ):
            if route.get(field) is not None:
                numbers.add(Decimal(str(route[field])).normalize())
        numbers.add(Decimal(str(len(route["checkpoints"]))).normalize())
        for checkpoint in route["checkpoints"]:
            for field in ("mile", "windMph", "rainInHr", "snowInHr", "temperatureF"):
                value = checkpoint.get(field)
                if value is not None:
                    numbers.add(Decimal(str(value)).normalize())
    return numbers
