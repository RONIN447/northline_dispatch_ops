"""Fault injection tests for the independent briefing evaluation checks."""

import json
import unittest

from briefing.providers import MockProvider
from briefing.schema import Briefing
from briefing.validator import enforce
from evals.checks import evaluate_checks
from evals.scenarios import load_scenarios


class BriefingCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scenarios = load_scenarios()
        cls.severe_scenario = next(
            scenario
            for scenario in scenarios
            if scenario["category"] == "severe_or_no_travel"
        )
        cls.gap_scenario = next(
            scenario
            for scenario in scenarios
            if scenario["category"] == "forecast_unavailable"
        )

    def test_each_check_fails_for_a_matching_faulty_mock_and_final_passes(self):
        cases = (
            ("faulty_route", self.severe_scenario, "route_matches_engine"),
            ("faulty_missing_checkpoint", self.severe_scenario, "severe_coverage"),
            ("faulty_downgrade", self.severe_scenario, "no_risk_downgrade"),
            ("faulty_no_gap", self.gap_scenario, "no_false_safe"),
            ("faulty_safe", self.severe_scenario, "no_false_safe"),
            ("faulty_number", self.severe_scenario, "numbers_grounded"),
            ("faulty_route_id", self.severe_scenario, "route_ids_grounded"),
            ("faulty_place", self.severe_scenario, "place_names_grounded"),
        )
        for mode, scenario, failed_check in cases:
            with self.subTest(mode=mode, check=failed_check):
                response = MockProvider(mode).generate("", json.dumps(scenario["plan"]))
                raw = Briefing.model_validate_json(response.text)
                raw_checks = evaluate_checks(raw, scenario["plan"])
                self.assertFalse(raw_checks[failed_check])

                final, _, _ = enforce(scenario["plan"], raw)
                final_checks = evaluate_checks(final, scenario["plan"])
                self.assertTrue(all(final_checks.values()), final_checks)

    def test_rule_based_mock_passes_all_checks_on_all_scenarios(self):
        for scenario in load_scenarios():
            with self.subTest(scenario=scenario["id"]):
                response = MockProvider("normal").generate(
                    "", json.dumps(scenario["plan"])
                )
                briefing = Briefing.model_validate_json(response.text)
                self.assertTrue(
                    all(evaluate_checks(briefing, scenario["plan"]).values())
                )
