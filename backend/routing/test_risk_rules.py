import unittest

from routing.views import classify_checkpoint_risk, parse_departure


class RiskClassificationTests(unittest.TestCase):
    def test_wind_threshold_at_55_is_no_travel(self):
        self.assertEqual(classify_checkpoint_risk(55, 0, 0, 20000), "No Travel")

    def test_heavy_load_elevates_high_wind_to_no_travel(self):
        self.assertEqual(classify_checkpoint_risk(47, 0, 0, 45000), "No Travel")

    def test_heavy_load_escalates_mid_wind_to_severe(self):
        self.assertEqual(classify_checkpoint_risk(42, 0, 0, 50000), "Severe")

    def test_rain_and_snow_rules_are_applied(self):
        self.assertEqual(classify_checkpoint_risk(10, 0.6, 0.0, 20000), "Severe")
        self.assertEqual(classify_checkpoint_risk(10, 0.0, 2.5, 20000), "Severe")


class RouteInputValidationTests(unittest.TestCase):
    def test_parse_departure_accepts_extended_fractional_precision(self):
        parsed = parse_departure("2026-10-10T12:00:00.1234567+05:30")
        self.assertEqual(parsed.isoformat(), "2026-10-10T06:30:00.123456+00:00")

    def test_parse_departure_accepts_naive_local_datetime(self):
        parsed = parse_departure("2026-10-10T12:00")
        self.assertEqual(parsed.isoformat(), "2026-10-10T12:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
