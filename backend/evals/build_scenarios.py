"""Build deterministic, engine-consistent briefing evaluation scenarios."""

import copy
import json
from collections import Counter
from pathlib import Path

from routing.risk_levels import RISK_LEVELS
from routing.views import (
    parse_checkpoint_spacing,
    parse_load_weight,
    rank_route_summaries,
    recompute_route_risk_summary,
)

EVALS_DIR = Path(__file__).resolve().parent
RAW_DIR = EVALS_DIR / "scenarios" / "raw"
SCENARIOS_DIR = EVALS_DIR / "scenarios"
WEATHER_FIELDS = ("windMph", "rainInHr", "snowInHr")


def _load_captures():
    manifest = json.loads((RAW_DIR / "manifest.json").read_text(encoding="utf-8"))
    captures = {}
    for entry in manifest["scenarios"]:
        plan = json.loads(
            (RAW_DIR / entry["response_file"]).read_text(encoding="utf-8")
        )
        captures[entry["id"]] = {
            "plan": plan,
            "request": entry["request"],
        }
    return captures


def _recompute_plan(plan, load_weight):
    recomputed_routes = [
        recompute_route_risk_summary(route, load_weight)
        for route in plan["routes"]
    ]
    plan["routes"] = rank_route_summaries(recomputed_routes)
    plan["recommendedRouteId"] = plan["routes"][0]["id"]
    return plan


def _strip_geometry(plan):
    for route in plan["routes"]:
        route.pop("geometry", None)
        for checkpoint in route["checkpoints"]:
            checkpoint.pop("lat", None)
            checkpoint.pop("lon", None)
    return plan


def _make_scenario(
    scenario_id,
    category,
    description,
    tags,
    capture,
    load_weight=None,
    mutate=None,
):
    plan = copy.deepcopy(capture["plan"])
    request = capture["request"]
    weight = parse_load_weight(
        request["loadWeight"] if load_weight is None else load_weight
    )
    if mutate is not None:
        mutate(plan)
    plan = _strip_geometry(_recompute_plan(plan, weight))
    return {
        "id": scenario_id,
        "category": category,
        "description": description,
        "tags": tags,
        "engine_input": {
            "load_weight_lbs": weight,
            "interval_miles": parse_checkpoint_spacing(request["intervalMiles"]),
            "departure": request["departure"],
        },
        "plan": plan,
    }


def _recommended_route(plan):
    return next(
        route
        for route in plan["routes"]
        if route["id"] == plan["recommendedRouteId"]
    )


def _weather_zeroed(plan):
    for route in plan["routes"]:
        for checkpoint in route["checkpoints"]:
            checkpoint["windMph"] = 0
            checkpoint["rainInHr"] = 0
            checkpoint["snowInHr"] = 0


def build_scenarios():
    captures = _load_captures()
    scenarios = []

    for capture_id, capture in captures.items():
        scenarios.append(
            _make_scenario(
                "normal_{}".format(capture_id),
                "normal_trip",
                "Captured baseline trip with engine-recomputed risks.",
                ["captured", "baseline"],
                capture,
            )
        )

    severe_captures = (
        "sfo_to_lax",
        "seattle_to_portland",
        "denver_to_salt_lake_city",
        "chicago_to_detroit",
        "dallas_to_houston",
    )
    severe_winds = (45.0, 48.0, 50.0, 54.9, 55.0)
    for index, (capture_id, wind) in enumerate(
        zip(severe_captures, severe_winds), start=1
    ):
        scenario_id = "severe_{}_{}".format(index, capture_id)

        def add_severe_checkpoint(plan, wind_speed=wind):
            route = _recommended_route(plan)
            checkpoint = route["checkpoints"][min(1, len(route["checkpoints"]) - 1)]
            checkpoint["windMph"] = wind_speed
            checkpoint["rainInHr"] = 0
            checkpoint["snowInHr"] = 0

        risk_name = "No Travel" if wind >= 55 else "Severe"
        scenarios.append(
            _make_scenario(
                scenario_id,
                "severe_or_no_travel",
                "Adds a {} mph wind checkpoint rated {} by the engine.".format(
                    wind, risk_name
                ),
                ["synthetic", "wind_{}mph".format(wind), "expected_{}".format(risk_name)],
                captures[capture_id],
                load_weight=28_000,
                mutate=add_severe_checkpoint,
            )
        )

    gap_captures = (
        "sfo_to_lax",
        "seattle_to_portland",
        "denver_to_salt_lake_city",
        "chicago_to_detroit",
        "dallas_to_houston",
    )
    for index, capture_id in enumerate(gap_captures, start=1):
        def remove_wind_forecast(plan):
            route = _recommended_route(plan)
            checkpoint = route["checkpoints"][min(2, len(route["checkpoints"]) - 1)]
            checkpoint["windMph"] = None

        scenarios.append(
            _make_scenario(
                "forecast_gap_{}_{}".format(index, capture_id),
                "forecast_unavailable",
                "Wind forecast is unavailable at one recommended-route checkpoint.",
                ["synthetic", "forecast_gap", "wind_unavailable"],
                captures[capture_id],
                mutate=remove_wind_forecast,
            )
        )

    threshold_cases = (
        ("wind_44_9_load_41000", 44.9, 41_000, "Severe"),
        ("wind_45_0_load_30000", 45.0, 30_000, "Severe"),
        ("wind_45_0_load_30001", 45.0, 30_001, "No Travel"),
        ("wind_35_0_load_40000", 35.0, 40_000, "High"),
    )
    for case_id, wind, load_weight, expected_risk in threshold_cases:
        def set_threshold_checkpoint(plan, wind_speed=wind):
            _weather_zeroed(plan)
            route = _recommended_route(plan)
            checkpoint = route["checkpoints"][min(1, len(route["checkpoints"]) - 1)]
            checkpoint["windMph"] = wind_speed

        scenarios.append(
            _make_scenario(
                "threshold_{}".format(case_id),
                "threshold_boundary",
                "Boundary check: {} mph wind with {:,} lb load should rate {}.".format(
                    wind, load_weight, expected_risk
                ),
                [
                    "synthetic",
                    "wind_{}mph".format(wind),
                    "load_{}lb".format(load_weight),
                    "expected_{}".format(expected_risk),
                ],
                captures["sfo_to_lax"],
                load_weight=load_weight,
                mutate=set_threshold_checkpoint,
            )
        )

    risky_captures = ("sfo_to_lax", "denver_to_salt_lake_city", "boston_to_new_york")
    for index, capture_id in enumerate(risky_captures, start=1):
        def make_all_routes_risky(plan):
            for route in plan["routes"]:
                for checkpoint in route["checkpoints"]:
                    checkpoint["windMph"] = 36
                    checkpoint["rainInHr"] = 0
                    checkpoint["snowInHr"] = 0

        scenarios.append(
            _make_scenario(
                "all_routes_risky_{}_{}".format(index, capture_id),
                "all_routes_risky",
                "All routes have High wind risk at every checkpoint.",
                ["synthetic", "all_routes_risky", "wind_36mph"],
                captures[capture_id],
                load_weight=28_000,
                mutate=make_all_routes_risky,
            )
        )

    near_tie_captures = ("sfo_to_lax", "chicago_to_detroit", "boston_to_new_york")
    for index, capture_id in enumerate(near_tie_captures, start=1):
        def make_routes_near_tied(plan):
            _weather_zeroed(plan)

        scenario = _make_scenario(
            "near_tie_{}_{}".format(index, capture_id),
            "near_tie_routes",
            "Routes have equal weather risk and closely matched travel times.",
            ["captured", "synthetic_weather", "near_tie"],
            captures[capture_id],
            mutate=make_routes_near_tied,
        )
        travel_times = sorted(route["durationHours"] for route in scenario["plan"]["routes"])
        if len(travel_times) < 2 or travel_times[1] - travel_times[0] > 0.5:
            raise ValueError(
                "Capture {} does not provide a near-tie route pair.".format(capture_id)
            )
        scenarios.append(scenario)

    return scenarios


def _risk_counts(plan):
    counts = Counter(
        checkpoint["risk"]
        for route in plan["routes"]
        for checkpoint in route["checkpoints"]
    )
    return " ".join(
        "{}:{}".format(level, counts[level]) for level in RISK_LEVELS
    )


def print_summary(scenarios):
    headers = ("ID", "CATEGORY", "RISK COUNTS", "GAP CHECKPOINTS", "RECOMMENDED")
    rows = []
    for scenario in scenarios:
        plan = scenario["plan"]
        gaps = sum(
            any(checkpoint.get(field) is None for field in WEATHER_FIELDS)
            for route in plan["routes"]
            for checkpoint in route["checkpoints"]
        )
        rows.append(
            (
                scenario["id"],
                scenario["category"],
                _risk_counts(plan),
                str(gaps),
                plan["recommendedRouteId"],
            )
        )
    widths = [
        max(len(headers[column]), *(len(row[column]) for row in rows))
        for column in range(len(headers))
    ]
    print(" | ".join(header.ljust(widths[i]) for i, header in enumerate(headers)))
    print("-+-".join("-" * width for width in widths))
    for row in rows:
        print(" | ".join(value.ljust(widths[i]) for i, value in enumerate(row)))


def write_scenarios(scenarios):
    SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)
    expected_files = set()
    for scenario in scenarios:
        file_path = SCENARIOS_DIR / "{}.golden.json".format(scenario["id"])
        expected_files.add(file_path.name)
        file_path.write_text(
            json.dumps(scenario, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    for old_file in SCENARIOS_DIR.glob("*.golden.json"):
        if old_file.name not in expected_files:
            old_file.unlink()


def main():
    scenarios = build_scenarios()
    write_scenarios(scenarios)
    print_summary(scenarios)


if __name__ == "__main__":
    main()
