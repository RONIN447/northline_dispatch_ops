import unittest
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import patch

from django.test import RequestFactory

from routing.views import (
    WeatherDataUnavailable,
    build_route_summary,
    classify_checkpoint_risk,
    coordinate_at_route_fraction,
    get_weather_at,
    get_weather_for_locations,
    forecast_days_for_locations,
    health_check,
    plan_route,
    parse_checkpoint_spacing,
    parse_departure,
    parse_load_weight,
    parse_location_name,
)


class RiskClassificationTests(unittest.TestCase):
    def test_wind_boundaries(self):
        cases = (
            (24.99, "Low"),
            (25, "Moderate"),
            (34.99, "Moderate"),
            (35, "High"),
            (44.99, "High"),
            (45, "Severe"),
            (54.99, "Severe"),
            (55, "No Travel"),
        )
        for wind, expected in cases:
            with self.subTest(wind=wind):
                self.assertEqual(classify_checkpoint_risk(wind, 0, 0, 20_000), expected)

    def test_rain_boundaries(self):
        cases = (
            (0.099, "Low"),
            (0.10, "Moderate"),
            (0.249, "Moderate"),
            (0.25, "High"),
            (0.499, "High"),
            (0.50, "Severe"),
            (1.00, "Severe"),
            (1.001, "No Travel"),
        )
        for rain, expected in cases:
            with self.subTest(rain=rain):
                self.assertEqual(classify_checkpoint_risk(0, rain, 0, 20_000), expected)

    def test_snow_boundaries(self):
        cases = (
            (0.499, "Low"),
            (0.5, "Moderate"),
            (0.999, "Moderate"),
            (1.0, "High"),
            (1.999, "High"),
            (2.0, "Severe"),
            (3.0, "Severe"),
            (3.001, "No Travel"),
        )
        for snow, expected in cases:
            with self.subTest(snow=snow):
                self.assertEqual(classify_checkpoint_risk(0, 0, snow, 20_000), expected)

    def test_load_thresholds_are_strictly_greater_than_the_assessment_values(self):
        self.assertEqual(classify_checkpoint_risk(45, 0, 0, 30_000), "Severe")
        self.assertEqual(classify_checkpoint_risk(45, 0, 0, 30_000.01), "No Travel")
        self.assertEqual(classify_checkpoint_risk(35, 0, 0, 40_000), "High")
        self.assertEqual(classify_checkpoint_risk(35, 0, 0, 40_000.01), "Severe")

    def test_highest_weather_risk_wins(self):
        self.assertEqual(classify_checkpoint_risk(25, 0.6, 0.5, 20_000), "Severe")


class InputValidationTests(unittest.TestCase):
    def test_departure_normalizes_timezone_and_fractional_precision(self):
        parsed = parse_departure("2026-10-10T12:00:00.1234567+05:30")
        self.assertEqual(parsed.isoformat(), "2026-10-10T06:30:00.123456+00:00")

    def test_naive_departure_uses_utc_and_z_suffix_is_accepted(self):
        self.assertEqual(
            parse_departure("2026-10-10T12:00").isoformat(),
            "2026-10-10T12:00:00+00:00",
        )
        self.assertEqual(
            parse_departure("2026-10-10T12:00:00Z").isoformat(),
            "2026-10-10T12:00:00+00:00",
        )

    def test_rejects_empty_or_malformed_departures(self):
        for value in ("", "not a date", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_departure(value)

    def test_load_weight_accepts_zero_and_rejects_invalid_values(self):
        self.assertEqual(parse_load_weight("0"), 0)
        self.assertEqual(parse_load_weight("40000.5"), 40_000.5)
        for value in ("", "heavy", "-1", "nan", "inf", "-inf", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_load_weight(value)

    def test_checkpoint_spacing_accepts_only_supported_integers(self):
        for value in ("10", 25, 50.0):
            with self.subTest(value=value):
                self.assertIn(parse_checkpoint_spacing(value), (10, 25, 50))
        for value in (0, -10, 10.5, "25.1", "many", "nan", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_checkpoint_spacing(value)

    def test_location_names_are_required_and_trimmed(self):
        self.assertEqual(parse_location_name("  Denver, CO ", "Origin"), "Denver, CO")
        for value in ("", "   ", None, 42):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_location_name(value, "Origin")


class RouteGeometryTests(unittest.TestCase):
    def test_coordinate_at_start_middle_and_end(self):
        route = [[-120.0, 36.0], [-118.0, 36.0]]
        self.assertEqual(coordinate_at_route_fraction(route, 0), route[0])
        self.assertAlmostEqual(coordinate_at_route_fraction(route, 0.5)[0], -119.0)
        self.assertEqual(coordinate_at_route_fraction(route, 1), route[-1])

    def test_single_point_route_and_invalid_geometry(self):
        point = [-120.0, 36.0]
        self.assertEqual(coordinate_at_route_fraction([point], 0.5), point)
        with self.assertRaises(ValueError):
            coordinate_at_route_fraction([], 0.5)
        with self.assertRaises(ValueError):
            coordinate_at_route_fraction([point], 1.1)

    @patch("routing.views.get_weather_for_locations")
    def test_route_summary_keeps_no_travel_separate_from_severe(self, get_weather):
        weather = {
            "windMph": 55,
            "rainInHr": 0,
            "snowInHr": 0,
            "temperatureF": 70,
            "forecastHour": "2026-10-10T12:00",
        }
        get_weather.side_effect = lambda locations: [weather for _ in locations]
        summary = build_route_summary(
            {
                "distance": 1609.344,
                "duration": 3600,
                "geometry": {"coordinates": [[-120, 36], [-119.98, 36]]},
            },
            {"label": "Origin"},
            {"label": "Destination"},
            datetime(2026, 10, 10, 12, tzinfo=timezone.utc),
            20_000,
            10,
            1,
        )
        self.assertEqual(summary["noTravelMiles"], 1.0)
        self.assertEqual(summary["severeMiles"], 1.0)


class WeatherForecastTests(unittest.TestCase):
    def setUp(self):
        self.arrival = datetime(2026, 10, 10, 12, 20, tzinfo=timezone.utc)
        self.hourly = {
            "time": ["2026-10-10T11:00", "2026-10-10T12:00", "2026-10-10T13:00"],
            "temperature_2m": [20, 21, 22],
            "wind_speed_10m": [10, 30, 12],
            "rain": [0, 0.25, 0],
            "snowfall": [0, 0.5, 0],
        }

    def mock_response(self, hourly):
        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {"hourly": hourly}

        return Response()

    @patch("routing.views.requests.get")
    def test_uses_nearest_hour_and_returns_expected_weather(self, get):
        get.return_value = self.mock_response(self.hourly)
        weather = get_weather_at(37, -120, self.arrival)
        self.assertEqual(weather["windMph"], 30)
        self.assertEqual(weather["rainInHr"], 0.25)
        self.assertEqual(weather["snowInHr"], 0.5)
        self.assertAlmostEqual(weather["temperatureF"], 69.8)
        self.assertEqual(get.call_args.kwargs["params"]["forecast_days"], 7)

    @patch("routing.views.requests.get")
    def test_fetches_multiple_checkpoint_forecasts_in_one_request(self, get):
        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return [{"hourly": self_hourly}, {"hourly": self_hourly}]

        self_hourly = self.hourly
        get.return_value = Response()
        locations = [
            (0, 37, -120, self.arrival),
            (25, 38, -121, self.arrival),
        ]

        weather = get_weather_for_locations(locations)

        self.assertEqual(len(weather), 2)
        self.assertTrue(all(item["windMph"] == 30 for item in weather))
        self.assertEqual(get.call_count, 1)
        self.assertEqual(
            get.call_args.kwargs["params"]["latitude"],
            "37.000000,38.000000",
        )
        self.assertEqual(
            get.call_args.kwargs["params"]["longitude"],
            "-120.000000,-121.000000",
        )
        self.assertEqual(get.call_args.kwargs["params"]["hourly"], "rain,snowfall,wind_speed_10m")

    def test_forecast_request_days_cover_arrival_without_always_fetching_seven(self):
        latest_arrival = datetime.now(timezone.utc).replace(microsecond=0)
        locations = [(0, 37, -120, latest_arrival)]
        self.assertEqual(forecast_days_for_locations(locations), 1)

        latest_arrival += timedelta(hours=36)
        locations = [(0, 37, -120, latest_arrival)]
        self.assertEqual(forecast_days_for_locations(locations), 3)

    @patch("routing.views.requests.get")
    def test_allows_subzero_temperature(self, get):
        hourly = dict(self.hourly)
        hourly["temperature_2m"] = [-6, -5, -4]
        get.return_value = self.mock_response(hourly)

        weather = get_weather_at(46.8, 9.8, self.arrival)

        self.assertAlmostEqual(weather["temperatureF"], 23.0)

    @patch("routing.views.requests.get")
    def test_empty_or_out_of_range_forecast_fails_closed(self, get):
        get.return_value = self.mock_response({"time": []})
        with self.assertRaises(WeatherDataUnavailable):
            get_weather_at(37, -120, self.arrival)

        get.return_value = self.mock_response(self.hourly)
        far_future = datetime(2026, 10, 20, tzinfo=timezone.utc)
        with self.assertRaises(WeatherDataUnavailable):
            get_weather_at(37, -120, far_future)

    @patch("routing.views.requests.get")
    def test_missing_or_invalid_risk_variable_fails_closed(self, get):
        missing_wind = dict(self.hourly)
        missing_wind["wind_speed_10m"] = [0, None, 0]
        get.return_value = self.mock_response(missing_wind)
        with self.assertRaises(WeatherDataUnavailable):
            get_weather_at(37, -120, self.arrival)

        invalid_rain = dict(self.hourly)
        invalid_rain["rain"] = [0, float("nan"), 0]
        get.return_value = self.mock_response(invalid_rain)
        with self.assertRaises(WeatherDataUnavailable):
            get_weather_at(37, -120, self.arrival)


class PlanRouteApiTests(unittest.TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.payload = {
            "origin": "San Francisco, CA",
            "destination": "Los Angeles, CA",
            "departure": "2026-10-10T12:00:00Z",
            "loadWeight": "28000",
            "intervalMiles": "25",
        }

    def test_health_check_returns_ok(self):
        response = health_check(self.factory.get("/api/health/"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content), {"status": "ok"})

    @patch("routing.views.get_weather_for_locations")
    @patch("routing.views.requests.get")
    @patch("routing.views.geocode_location")
    def test_plan_route_returns_three_ranked_route_options(
        self, geocode_location, requests_get, get_weather_for_locations
    ):
        geocode_location.side_effect = [
            {"lat": 37.77, "lon": -122.42, "label": "San Francisco, United States", "timezone": "UTC"},
            {"lat": 34.05, "lon": -118.24, "label": "Los Angeles, United States", "timezone": "UTC"},
        ]

        class RoutingResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "code": "Ok",
                    "routes": [
                        {
                            "distance": 100000,
                            "duration": 7236,
                            "geometry": {"coordinates": [[-122.42, 37.77], [-118.24, 34.05]]},
                            "weight_name": "fastest",
                        },
                        {
                            "distance": 105000,
                            "duration": 7200,
                            "geometry": {"coordinates": [[-122.42, 37.77], [-118.24, 34.05]]},
                            "weight_name": "alternative-1",
                        },
                        {
                            "distance": 110000,
                            "duration": 7272,
                            "geometry": {"coordinates": [[-122.42, 37.77], [-118.24, 34.05]]},
                            "weight_name": "alternative-2",
                        },
                    ],
                }

        requests_get.return_value = RoutingResponse()
        weather_result = {
            "windMph": 10,
            "rainInHr": 0,
            "snowInHr": 0,
            "temperatureF": 70,
            "forecastHour": "2026-10-10T12:00",
        }
        get_weather_for_locations.side_effect = lambda locations: [
            weather_result for _ in locations
        ]

        request = self.factory.post(
            "/api/plan/",
            data=json.dumps(self.payload),
            content_type="application/json",
        )
        response = plan_route(request)

        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(len(body["routes"]), 3)
        self.assertEqual(body["recommendedRouteId"], body["routes"][0]["id"])
        self.assertEqual(body["recommendedRouteId"], "route-2-alternative-1")
        self.assertTrue(all(route["checkpoints"] for route in body["routes"]))
        self.assertTrue(all("rankKey" not in route for route in body["routes"]))

    @patch("routing.views.geocode_location")
    def test_plan_route_rejects_missing_location_before_external_calls(self, geocode_location):
        self.payload["origin"] = "   "
        request = self.factory.post(
            "/api/plan/",
            data=json.dumps(self.payload),
            content_type="application/json",
        )
        response = plan_route(request)

        self.assertEqual(response.status_code, 400)
        self.assertIn("Origin is required", json.loads(response.content)["error"])
        geocode_location.assert_not_called()

if __name__ == "__main__":
    unittest.main()
