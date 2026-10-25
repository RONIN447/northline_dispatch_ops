"""Grounding checks for free-text briefing claims."""

import re
from decimal import Decimal, InvalidOperation

_NUMBER_PATTERN = re.compile(r"(?<![A-Za-z-])\d[\d,]*(?:\.\d+)?")
_ROUTE_ID_PATTERN = re.compile(r"\broute-[A-Za-z0-9_-]+\b", re.IGNORECASE)
_PLACE_PATTERN = re.compile(
    r"\b[A-Z][a-z]+(?:['-][A-Z]?[a-z]+)*(?:\s+[A-Z][a-z]+(?:['-][A-Z]?[a-z]+)*)*\b"
)
_NON_PLACE_WORDS = {
    "Recommended",
    "route",
    "Route",
    "Dispatch",
    "Estimated",
    "Review",
    "Severe",
    "No",
    "Travel",
    "High",
    "Low",
    "Moderate",
    "Wind",
    "Rain",
    "Snow",
    "Checkpoint",
    "Forecast",
    "Data",
    "Gap",
    "Hold",
    "Proceed",
    "Brief",
    "Driver",
    "Conditions",
    "Listed",
    "The",
    "This",
    "That",
    "These",
    "Those",
    "A",
    "An",
    "If",
    "When",
    "Please",
    "Monitor",
    "Consider",
    "Delay",
    "Reroute",
    "Until",
    "Reviewing",
    "At",
    "From",
    "To",
    "And",
    "Or",
    "For",
    "After",
    "Before",
    "Use",
    "Avoid",
    "Route",
}


def check_grounding(briefing, route_plan):
    """Return grounding violations in the summary and dispatcher actions."""
    claims = "{} {}".format(briefing.summary, " ".join(briefing.dispatcher_actions))
    errors = []
    route_ids = {route["id"] for route in route_plan["routes"]}

    unsupported_routes = {
        match.group()
        for match in _ROUTE_ID_PATTERN.finditer(claims)
        if match.group() not in route_ids
    }
    if unsupported_routes:
        errors.append("unsupported_route_id")
    if any(item.route_id not in route_ids for item in briefing.risky_checkpoints):
        errors.append("unsupported_route_id")

    allowed_numbers = _route_plan_numbers(route_plan)
    claims_without_route_ids = _ROUTE_ID_PATTERN.sub("", claims)
    for match in _NUMBER_PATTERN.finditer(claims_without_route_ids):
        try:
            number = Decimal(match.group().replace(",", "")).normalize()
        except InvalidOperation:
            continue
        if number not in allowed_numbers:
            errors.append("unsupported_number")
            break

    if _has_unsupported_place(claims, route_plan):
        errors.append("unsupported_place_name")
    return errors


def _has_unsupported_place(claims, route_plan):
    allowed_words = set()
    for location_key in ("origin", "destination"):
        location = route_plan.get(location_key, {})
        if isinstance(location, dict):
            for value in location.values():
                if isinstance(value, str):
                    allowed_words.update(_place_words(value))
    for route in route_plan["routes"]:
        summary = route.get("summary", "")
        if isinstance(summary, str):
            allowed_words.update(_place_words(summary))

    for match in _PLACE_PATTERN.finditer(claims):
        phrase = match.group()
        words = phrase.split()
        for index, word in enumerate(words):
            if word in allowed_words or word in _NON_PLACE_WORDS:
                continue
            return True
    return False


def _place_words(value):
    return {
        word
        for word in re.findall(r"[A-Za-z]+(?:['-][A-Za-z]+)*", value)
        if word[:1].isupper()
    }


def _route_plan_numbers(route_plan):
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
            value = route.get(field)
            if value is not None:
                numbers.add(Decimal(str(value)).normalize())
        numbers.add(Decimal(str(len(route["checkpoints"]))).normalize())
        for checkpoint in route["checkpoints"]:
            for field in ("mile", "windMph", "rainInHr", "snowInHr", "temperatureF"):
                value = checkpoint.get(field)
                if value is not None:
                    numbers.add(Decimal(str(value)).normalize())
    return numbers
