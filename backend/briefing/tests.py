from pathlib import Path
import unittest

from pydantic import ValidationError

from briefing.schema import BriefingRoutePlan
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
