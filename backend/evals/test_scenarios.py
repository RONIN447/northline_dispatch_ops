import os
import unittest
from collections import Counter
from pathlib import Path

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")
django.setup()

from briefing.views import _validate_plan_shape
from evals.scenarios import EXPECTED_CATEGORY_COUNTS, load_scenarios
from routing.risk_levels import HIGH, LOW, NO_TRAVEL, RISK_SCORES
from routing.views import rank_route_summaries, recompute_route_risk_summary

SCENARIO_DIR = Path(__file__).resolve().parent / "scenarios"


class GoldenScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenarios = load_scenarios()

    def test_every_scenario_loads_and_passes_briefing_request_validation(self):
        self.assertTrue(self.scenarios)
        scenario_ids = set()
        for scenario in self.scenarios:
            with self.subTest(scenario=scenario.get("id")):
                self.assertEqual(
                    {"id", "category", "description", "tags", "plan"},
                    {"id", "category", "description", "tags", "plan"} & set(scenario),
                )
                self.assertNotIn(scenario["id"], scenario_ids)
                scenario_ids.add(scenario["id"])
                self.assertIsInstance(scenario["tags"], list)
                self.assertIsInstance(scenario["engine_input"]["load_weight_lbs"], (int, float))
                self.assertIsNone(_validate_plan_shape(scenario["plan"]))
                for route in scenario["plan"]["routes"]:
                    self.assertNotIn("geometry", route)
                    for checkpoint in route["checkpoints"]:
                        self.assertNotIn("lat", checkpoint)
                        self.assertNotIn("lon", checkpoint)

    def test_each_category_has_the_expected_count(self):
        counts = Counter(scenario["category"] for scenario in self.scenarios)
        self.assertEqual(dict(counts), EXPECTED_CATEGORY_COUNTS)
        self.assertEqual(len(self.scenarios), 28)
        self.assertEqual(
            len(list(SCENARIO_DIR.glob("*.golden.json"))),
            len(self.scenarios),
        )

    def test_risks_summaries_and_recommendations_match_engine_recomputation(self):
        for scenario in self.scenarios:
            with self.subTest(scenario=scenario["id"]):
                plan = scenario["plan"]
                load_weight = scenario["engine_input"]["load_weight_lbs"]
                expected_routes = [
                    recompute_route_risk_summary(route, load_weight)
                    for route in plan["routes"]
                ]
                expected_routes = rank_route_summaries(expected_routes)

                self.assertEqual(
                    [route["id"] for route in plan["routes"]],
                    [route["id"] for route in expected_routes],
                )
                self.assertEqual(
                    plan["recommendedRouteId"],
                    expected_routes[0]["id"],
                )
                for actual, expected in zip(plan["routes"], expected_routes):
                    self.assertEqual(actual["recommended"], expected["recommended"])
                    self.assertEqual(actual["severeMiles"], expected["severeMiles"])
                    self.assertEqual(actual["highMiles"], expected["highMiles"])
                    self.assertEqual(actual["noTravelMiles"], expected["noTravelMiles"])
                    self.assertEqual(actual["averageRisk"], expected["averageRisk"])
                    self.assertEqual(
                        [item["risk"] for item in actual["checkpoints"]],
                        [item["risk"] for item in expected["checkpoints"]],
                    )

    def test_severe_scenarios_include_severe_or_no_travel_checkpoints(self):
        scenarios = self._in_category("severe_or_no_travel")
        for scenario in scenarios:
            risks = self._all_risks(scenario)
            self.assertTrue(any(risk in ("Severe", NO_TRAVEL) for risk in risks))
        self.assertTrue(
            any(
                NO_TRAVEL in self._all_risks(scenario)
                for scenario in scenarios
            )
        )

    def test_forecast_gap_scenarios_mark_unavailable_weather_and_raise_risk(self):
        scenarios = self._in_category("forecast_unavailable")
        for scenario in scenarios:
            with self.subTest(scenario=scenario["id"]):
                gap_checkpoints = [
                    checkpoint
                    for route in scenario["plan"]["routes"]
                    for checkpoint in route["checkpoints"]
                    if any(
                        checkpoint.get(field) is None
                        for field in ("windMph", "rainInHr", "snowInHr")
                    )
                ]
                self.assertEqual(len(gap_checkpoints), 1)
                self.assertGreaterEqual(
                    RISK_SCORES[gap_checkpoints[0]["risk"]],
                    RISK_SCORES["Severe"],
                )

    def test_threshold_boundary_scenarios_match_risk_table(self):
        expected_by_id = {
            "threshold_wind_44_9_load_41000": ("Severe", 44.9, 41_000),
            "threshold_wind_45_0_load_30000": ("Severe", 45.0, 30_000),
            "threshold_wind_45_0_load_30001": ("No Travel", 45.0, 30_001),
            "threshold_wind_35_0_load_40000": ("High", 35.0, 40_000),
        }
        scenarios = self._in_category("threshold_boundary")
        self.assertEqual({scenario["id"] for scenario in scenarios}, set(expected_by_id))
        for scenario in scenarios:
            with self.subTest(scenario=scenario["id"]):
                risks = self._all_risks(scenario)
                expected_risk, expected_wind, expected_load = expected_by_id[
                    scenario["id"]
                ]
                self.assertEqual(
                    scenario["engine_input"]["load_weight_lbs"],
                    expected_load,
                )
                target_checkpoints = [
                    checkpoint
                    for route in scenario["plan"]["routes"]
                    for checkpoint in route["checkpoints"]
                    if checkpoint["windMph"] == expected_wind
                ]
                self.assertEqual(len(target_checkpoints), 1)
                self.assertEqual(target_checkpoints[0]["risk"], expected_risk)
                self.assertEqual(risks.count(expected_risk), 1)
                self.assertEqual(
                    sum(risk != LOW for risk in risks),
                    1,
                )

    def test_all_routes_risky_scenarios_have_high_or_greater_risk_on_each_route(self):
        for scenario in self._in_category("all_routes_risky"):
            with self.subTest(scenario=scenario["id"]):
                self.assertEqual(len(scenario["plan"]["routes"]), 3)
                for route in scenario["plan"]["routes"]:
                    self.assertTrue(route["checkpoints"])
                    self.assertTrue(
                        all(
                            RISK_SCORES[checkpoint["risk"]] >= RISK_SCORES[HIGH]
                            for checkpoint in route["checkpoints"]
                        )
                    )

    def test_near_tie_scenarios_rank_low_risk_routes_with_close_durations(self):
        for scenario in self._in_category("near_tie_routes"):
            with self.subTest(scenario=scenario["id"]):
                plan = scenario["plan"]
                durations = sorted(route["durationHours"] for route in plan["routes"])
                self.assertLessEqual(durations[1] - durations[0], 0.5)
                self.assertTrue(
                    all(
                        checkpoint["risk"] == LOW
                        for route in plan["routes"]
                        for checkpoint in route["checkpoints"]
                    )
                )
                self.assertTrue(
                    all(
                        route["highMiles"] == route["severeMiles"] == route["noTravelMiles"] == 0
                        for route in plan["routes"]
                    )
                )

    def _in_category(self, category):
        return [
            scenario
            for scenario in self.scenarios
            if scenario["category"] == category
        ]

    @staticmethod
    def _all_risks(scenario):
        return [
            checkpoint["risk"]
            for route in scenario["plan"]["routes"]
            for checkpoint in route["checkpoints"]
        ]
