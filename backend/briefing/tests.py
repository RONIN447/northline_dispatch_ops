import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from briefing.providers import MockProvider, get_provider
from briefing.schema import Briefing, BriefingRoutePlan
from evals.checks import validate_briefing
from routing.risk_levels import RISK_LEVELS


class BriefingRoutePlanTests(unittest.TestCase):
    def test_validates_captured_live_plan_responses(self):
        raw_responses = Path(__file__).resolve().parents[1] / "evals" / "scenarios" / "raw"
        response_files = sorted(raw_responses.glob("*.response.json"))

        self.assertEqual(len(response_files), 8)
        for response_file in response_files:
            with self.subTest(scenario=response_file.name):
                plan = BriefingRoutePlan.model_validate_json(
                    response_file.read_text(encoding="utf-8")
                )
                self.assertEqual(len(plan.routes), 3)
                self.assertIn(plan.recommendedRouteId, [route.id for route in plan.routes])

    def test_accepts_missing_optional_forecast_values(self):
        payload = self._minimal_plan()
        checkpoint = payload["routes"][0]["checkpoints"][0]
        checkpoint["temperatureF"] = None
        checkpoint.pop("forecastHour")

        plan = BriefingRoutePlan.model_validate(payload)

        self.assertIsNone(plan.routes[0].checkpoints[0].temperatureF)
        self.assertIsNone(plan.routes[0].checkpoints[0].forecastHour)

    def test_rejects_risk_level_outside_canonical_order(self):
        payload = self._minimal_plan()
        payload["routes"][0]["checkpoints"][0]["risk"] = "Extreme"

        with self.assertRaises(ValidationError):
            BriefingRoutePlan.model_validate(payload)

    def test_risk_validator_uses_canonical_levels(self):
        payload = self._minimal_plan()
        payload["routes"][0]["checkpoints"][0]["risk"] = RISK_LEVELS[-1]

        plan = BriefingRoutePlan.model_validate(payload)

        self.assertEqual(plan.routes[0].checkpoints[0].risk, RISK_LEVELS[-1])

    def test_rejects_recommended_route_id_not_in_routes(self):
        payload = self._minimal_plan()
        payload["recommendedRouteId"] = "missing-route"

        with self.assertRaises(ValidationError):
            BriefingRoutePlan.model_validate(payload)

    @staticmethod
    def _minimal_plan():
        return {
            "origin": {"label": "Origin", "lat": 1, "lon": 2, "timezone": "UTC"},
            "destination": {"label": "Destination", "lat": 3, "lon": 4, "timezone": "UTC"},
            "routes": [
                {
                    "id": "route-1",
                    "distanceMiles": 10,
                    "durationHours": 1,
                    "arrival": "2026-10-25T12:00:00+00:00",
                    "geometry": [[2, 1], [4, 3]],
                    "checkpoints": [
                        {
                            "mile": 0,
                            "lat": 1,
                            "lon": 2,
                            "eta": "2026-10-25T11:00:00+00:00",
                            "windMph": 10,
                            "rainInHr": 0,
                            "snowInHr": 0,
                            "forecastHour": "2026-10-25T11:00",
                            "risk": "Low",
                        }
                    ],
                    "severeMiles": 0,
                    "highMiles": 0,
                    "noTravelMiles": 0,
                    "averageRisk": 0,
                    "summary": "10 miles",
                    "recommended": True,
                }
            ],
            "recommendedRouteId": "route-1",
            "forecastHours": 48,
        }


class BriefingProviderTests(unittest.TestCase):
    def setUp(self):
        response_file = (
            Path(__file__).resolve().parents[1]
            / "evals"
            / "scenarios"
            / "raw"
            / "01_sfo_to_lax.response.json"
        )
        self.route_plan = json.loads(response_file.read_text(encoding="utf-8"))
        recommended_route = next(
            route
            for route in self.route_plan["routes"]
            if route["id"] == self.route_plan["recommendedRouteId"]
        )
        recommended_route["checkpoints"][0]["risk"] = "Severe"
        self.user = json.dumps(self.route_plan)

    def test_normal_mock_produces_a_briefing_that_passes_checks(self):
        response = MockProvider(mode="normal").generate("Return briefing JSON.", self.user)
        briefing = Briefing.model_validate_json(response.text)

        self.assertGreater(response.tokens, 0)
        self.assertGreaterEqual(response.latency_ms, 0)
        self.assertEqual(validate_briefing(briefing, self.route_plan), [])

    def test_faulty_mock_is_caught_for_route_risk_and_invented_number(self):
        response = MockProvider(mode="faulty").generate("Return briefing JSON.", self.user)
        briefing = Briefing.model_validate_json(response.text)

        self.assertEqual(
            set(validate_briefing(briefing, self.route_plan)),
            {
                "recommended_route_mismatch",
                "risky_checkpoint_mismatch",
                "unsupported_number",
            },
        )

    def test_faulty_downgrade_is_caught_by_shared_check(self):
        response = MockProvider(mode="faulty_downgrade").generate(
            "Return briefing JSON.", self.user
        )
        briefing = Briefing.model_validate_json(response.text)

        self.assertIn("risky_checkpoint_mismatch", validate_briefing(briefing, self.route_plan))

    def test_faulty_no_gap_is_caught_by_shared_check(self):
        checkpoint = self.route_plan["routes"][0]["checkpoints"][0]
        checkpoint.pop("windMph")
        user = json.dumps(self.route_plan)
        response = MockProvider(mode="faulty_no_gap").generate("Return briefing JSON.", user)
        briefing = Briefing.model_validate_json(response.text)

        self.assertIn("data_gap_mismatch", validate_briefing(briefing, self.route_plan))

    def test_provider_selection_uses_environment(self):
        with patch.dict(os.environ, {"LLM_PROVIDER": "mock", "MOCK_MODE": "faulty"}):
            provider = get_provider()

        self.assertIsInstance(provider, MockProvider)
        self.assertEqual(provider.mode, "faulty")

    def test_unknown_provider_is_an_error(self):
        with patch.dict(os.environ, {"LLM_PROVIDER": "unknown"}):
            with self.assertRaisesRegex(ValueError, "LLM_PROVIDER"):
                get_provider()

    def test_non_mock_provider_requires_an_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "ANTHROPIC_API_KEY"):
                get_provider("anthropic")
            with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY"):
                get_provider("openai")

    def test_non_mock_provider_requires_model_environment_variable(self):
        with patch.dict(
            os.environ,
            {
                "ANTHROPIC_API_KEY": "test-key",
                "OPENAI_API_KEY": "test-key",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "ANTHROPIC_MODEL"):
                get_provider("anthropic")
            with self.assertRaisesRegex(ValueError, "OPENAI_MODEL"):
                get_provider("openai")
