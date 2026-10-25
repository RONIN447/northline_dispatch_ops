"""Shared deterministic validation checks for generated dispatch briefings."""

import re
from typing import Dict, List, Tuple

from evals.grounding import check_grounding
from briefing.schema import Briefing
from routing.risk_levels import HIGH, RISK_SCORES, SEVERE

_WEATHER_FIELDS = ("windMph", "rainInHr", "snowInHr")
_FALSE_SAFE_CLAIM = re.compile(
    r"\b(?:safe(?:\s+to\s+(?:travel|drive|dispatch))?|"
    r"(?:the\s+)?route is clear|no\s+(?:weather\s+)?(?:risk|hazard)|"
    r"proceed with (?:the )?(?:recommended )?route)\b",
    re.IGNORECASE,
)


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

    expected_risks = set(expected_risky_checkpoints(route_plan))
    expected_gaps = set(expected_data_gaps(route_plan))

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

    if _has_false_safe_claim(briefing, route_plan):
        errors.append("false_safe_claim")

    errors.extend(check_grounding(briefing, route_plan))
    return errors


def _has_false_safe_claim(briefing: Briefing, route_plan: dict) -> bool:
    recommended_route = next(
        route
        for route in route_plan["routes"]
        if route["id"] == route_plan["recommendedRouteId"]
    )
    recommended_has_risk_or_gap = any(
        RISK_SCORES.get(checkpoint.get("risk"), 0) >= RISK_SCORES[HIGH]
        or any(checkpoint.get(field) is None for field in _WEATHER_FIELDS)
        for checkpoint in recommended_route["checkpoints"]
    )
    claims = "{} {}".format(briefing.summary, " ".join(briefing.dispatcher_actions))
    claims_without_negated_safe = re.sub(
        r"\b(?:not|never|do not|don't|cannot|can't)\s+(?:be\s+)?safe\b",
        "",
        claims,
        flags=re.IGNORECASE,
    )
    return recommended_has_risk_or_gap and bool(
        _FALSE_SAFE_CLAIM.search(claims_without_negated_safe)
    )


def evaluate_checks(briefing: Briefing, route_plan: dict) -> Dict[str, bool]:
    """Evaluate named safety and grounding checks independently."""
    route_ids = {route["id"] for route in route_plan["routes"]}
    routes_by_id = {route["id"]: route for route in route_plan["routes"]}
    actual = {}
    for item in briefing.risky_checkpoints:
        actual.setdefault((item.route_id, item.checkpoint_index), []).append(item.level)

    expected = {}
    severe_expected = set()
    for route in route_plan["routes"]:
        for index, checkpoint in enumerate(route["checkpoints"]):
            risk = checkpoint.get("risk")
            if risk not in RISK_SCORES:
                continue
            key = (route["id"], index)
            if RISK_SCORES[risk] >= RISK_SCORES[HIGH]:
                expected[key] = risk
            if RISK_SCORES[risk] >= RISK_SCORES[SEVERE]:
                severe_expected.add((route["id"], index, risk))

    actual_exact = {
        (route_id, index, level)
        for (route_id, index), levels in actual.items()
        for level in levels
    }
    severe_coverage = severe_expected.issubset(actual_exact)
    no_downgrade = True
    for (route_id, index), levels in actual.items():
        route = routes_by_id.get(route_id)
        if route is None or index < 0 or index >= len(route["checkpoints"]):
            no_downgrade = False
            continue
        engine_risk = route["checkpoints"][index].get("risk")
        if engine_risk not in RISK_SCORES:
            no_downgrade = False
            continue
        if any(
            level not in RISK_SCORES
            or RISK_SCORES[level] < RISK_SCORES[engine_risk]
            for level in levels
        ):
            no_downgrade = False

    expected_gaps = set(expected_data_gaps(route_plan))
    false_safe_claim = _has_false_safe_claim(briefing, route_plan)
    grounding_errors = check_grounding(briefing, route_plan)
    return {
        "route_matches_engine": (
            briefing.recommended_route_id == route_plan["recommendedRouteId"]
            and briefing.recommended_route_id in route_ids
        ),
        "severe_coverage": severe_coverage,
        "no_risk_downgrade": no_downgrade,
        "no_false_safe": (
            set(expected) == set(actual)
            and sum(len(levels) for levels in actual.values())
            == len(briefing.risky_checkpoints)
            and expected_gaps == set(briefing.data_gaps)
            and not false_safe_claim
        ),
        "numbers_grounded": "unsupported_number" not in grounding_errors,
        "route_ids_grounded": "unsupported_route_id" not in grounding_errors,
        "place_names_grounded": "unsupported_place_name" not in grounding_errors,
    }


def expected_risky_checkpoints(route_plan: dict) -> List[Tuple[str, int, str]]:
    """Return all engine-rated High-or-higher checkpoints in plan order."""
    expected = []
    for route in route_plan["routes"]:
        for index, checkpoint in enumerate(route["checkpoints"]):
            risk = checkpoint.get("risk")
            if risk in RISK_SCORES and RISK_SCORES[risk] >= RISK_SCORES[HIGH]:
                expected.append((route["id"], index, risk))
    return expected


def expected_data_gaps(route_plan: dict) -> List[str]:
    """Return canonical gap descriptions for missing checkpoint weather fields."""
    expected = []
    for route in route_plan["routes"]:
        for index, checkpoint in enumerate(route["checkpoints"]):
            missing = [field for field in _WEATHER_FIELDS if checkpoint.get(field) is None]
            if missing:
                expected.append(
                    "{} checkpoint {} is missing {}.".format(
                        route["id"], index, ", ".join(missing)
                    )
                )
    return expected
