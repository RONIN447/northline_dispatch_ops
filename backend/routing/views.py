"""Route planning and checkpoint weather scoring for Wayfinder."""

import json
import math
import re
from datetime import datetime, timezone

try:
    import importlib

    requests = importlib.import_module("requests")
except ModuleNotFoundError:
    class _MissingRequests:
        class RequestException(RuntimeError):
            """Fallback exception used when the requests dependency is unavailable."""

        @staticmethod
        def get(*args, **kwargs):
            raise RuntimeError(
                "The 'requests' package is not installed. Install project dependencies "
                "before using the routing API."
            )

    requests = _MissingRequests()

try:
    from django.http import JsonResponse  # type: ignore[import-not-found]
    from django.views.decorators.http import require_POST  # type: ignore[import-not-found]
except ModuleNotFoundError:
    class JsonResponse:
        """Fallback response object used when Django is unavailable."""

        def __init__(self, data=None, status=200, **kwargs):
            self.status_code = status
            self.data = data or {}

    def require_POST(view_func):
        """Fallback decorator used when Django is unavailable."""

        def _wrapped(*args, **kwargs):
            raise RuntimeError(
                "Django is not installed. Install project dependencies before using the routing API."
            )

        return _wrapped

ROUTING_API_URL = "https://router.project-osrm.org/route/v1/driving/"
GEOCODING_API_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_API_URL = "https://api.open-meteo.com/v1/forecast"

RISK_SCORES = {"Low": 0, "Moderate": 1, "High": 2, "Severe": 3, "No Travel": 4}
MILES_PER_KILOMETER = 0.621371


def parse_departure(value):
    """Normalize arbitrary ISO timestamps from browsers or external clients."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            raise ValueError("Departure time is required.")
        candidate = candidate.replace("Z", "+00:00")
        fraction_match = re.search(r"(\.\d+)", candidate)
        if fraction_match:
            fractional_part = fraction_match.group(1)
            candidate = (
                candidate[:fraction_match.start()]
                + fractional_part[:7]
                + candidate[fraction_match.end():]
            )
        dt = datetime.fromisoformat(candidate)
    else:
        raise ValueError("Departure time is required.")

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def geocode_location(location_name):
    response = requests.get(
        GEOCODING_API_URL,
        params={"name": location_name, "count": 1, "language": "en", "format": "json"},
        timeout=20,
    )
    response.raise_for_status()
    matches = response.json().get("results") or []
    if not matches:
        raise ValueError(f"Could not find location: {location_name}")

    match = matches[0]
    display_name = ", ".join(
        part for part in (match.get("name"), match.get("admin1"), match.get("country")) if part
    )
    return {
        "lat": match["latitude"],
        "lon": match["longitude"],
        "label": display_name,
        "timezone": match.get("timezone", "UTC"),
    }


def classify_checkpoint_risk(wind_mph, rain_inches_per_hour, snow_inches_per_hour, load_weight):
    """Return the highest applicable weather category after load adjustments."""
    if wind_mph >= 55:
        return "No Travel"
    if 45 <= wind_mph < 55 and load_weight > 30_000:
        return "No Travel"

    wind_risk = (
        "Low" if wind_mph < 25 else
        "Moderate" if wind_mph < 35 else
        "High" if wind_mph < 45 else
        "Severe"
    )
    rain_risk = (
        "Low" if rain_inches_per_hour < 0.10 else
        "Moderate" if rain_inches_per_hour < 0.25 else
        "High" if rain_inches_per_hour < 0.50 else
        "Severe" if rain_inches_per_hour <= 1.00 else
        "No Travel"
    )
    snow_risk = (
        "Low" if snow_inches_per_hour < 0.5 else
        "Moderate" if snow_inches_per_hour < 1.0 else
        "High" if snow_inches_per_hour < 2.0 else
        "Severe" if snow_inches_per_hour <= 3.0 else
        "No Travel"
    )

    highest_weather_risk = max(
        (wind_risk, rain_risk, snow_risk), key=RISK_SCORES.__getitem__
    )
    if 35 <= wind_mph < 45 and load_weight > 40_000:
        highest_weather_risk = max(
            (highest_weather_risk, "Severe"), key=RISK_SCORES.__getitem__
        )
    return highest_weather_risk


def get_weather_at(latitude, longitude, arrival_time):
    response = requests.get(
        WEATHER_API_URL,
        params={
            "latitude": latitude,
            "longitude": longitude,
            "hourly": "temperature_2m,precipitation,rain,snowfall,wind_speed_10m",
            "forecast_days": 3,
            "timezone": "UTC",
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
        },
        timeout=20,
    )
    response.raise_for_status()
    hourly_forecast = response.json().get("hourly", {})
    forecast_times = hourly_forecast.get("time", [])
    if not forecast_times:
        return {
            "windMph": 0,
            "rainInHr": 0,
            "snowInHr": 0,
            "temperatureF": None,
        }

    arrival_utc = arrival_time.astimezone(timezone.utc)
    forecast_index = min(
        range(len(forecast_times)),
        key=lambda index: abs(
            datetime.fromisoformat(forecast_times[index]).replace(tzinfo=timezone.utc)
            - arrival_utc
        ).total_seconds(),
    )

    def forecast_value(field_name):
        values = hourly_forecast.get(field_name, [])
        if forecast_index >= len(values) or values[forecast_index] is None:
            return 0.0
        return float(values[forecast_index])

    temperatures = hourly_forecast.get("temperature_2m", [])
    temperature_f = None
    if forecast_index < len(temperatures) and temperatures[forecast_index] is not None:
        temperature_f = forecast_value("temperature_2m") * 9 / 5 + 32

    return {
        "windMph": forecast_value("wind_speed_10m"),
        "rainInHr": forecast_value("rain"),
        "snowInHr": forecast_value("snowfall"),
        "temperatureF": temperature_f,
        "forecastHour": forecast_times[forecast_index],
    }


def coordinate_at_route_fraction(route_coordinates, route_fraction):
    """Find the coordinate at a fraction of the route's length."""
    segment_lengths_km = []
    for start, end in zip(route_coordinates, route_coordinates[1:]):
        start_lon, start_lat = start
        end_lon, end_lat = end
        start_lat_radians = math.radians(start_lat)
        end_lat_radians = math.radians(end_lat)
        latitude_delta = math.radians(end_lat - start_lat)
        longitude_delta = math.radians(end_lon - start_lon)
        haversine = (
            math.sin(latitude_delta / 2) ** 2
            + math.cos(start_lat_radians)
            * math.cos(end_lat_radians)
            * math.sin(longitude_delta / 2) ** 2
        )
        segment_lengths_km.append(2 * 6371 * math.asin(math.sqrt(haversine)))

    total_route_length = sum(segment_lengths_km)
    target_distance = total_route_length * route_fraction
    distance_travelled = 0

    for segment_index, segment_length in enumerate(segment_lengths_km):
        if distance_travelled + segment_length >= target_distance:
            segment_fraction = (
                (target_distance - distance_travelled) / segment_length
                if segment_length else 0
            )
            start = route_coordinates[segment_index]
            end = route_coordinates[segment_index + 1]
            return [
                start[0] + segment_fraction * (end[0] - start[0]),
                start[1] + segment_fraction * (end[1] - start[1]),
            ]
        distance_travelled += segment_length

    return route_coordinates[-1]


def build_route_summary(route_data, origin, destination, departure_time, load_weight, checkpoint_spacing):
    route_coordinates = route_data["geometry"]["coordinates"]
    distance_miles = route_data["distance"] / 1000 * MILES_PER_KILOMETER
    travel_hours = route_data["duration"] / 3600
    checkpoint_count = max(1, math.ceil(distance_miles / checkpoint_spacing))
    checkpoints = []

    for checkpoint_index in range(checkpoint_count + 1):
        distance_along_route = (
            min(distance_miles, checkpoint_index * checkpoint_spacing)
            if checkpoint_index < checkpoint_count else distance_miles
        )
        route_fraction = distance_along_route / distance_miles if distance_miles else 0
        longitude, latitude = coordinate_at_route_fraction(route_coordinates, route_fraction)
        arrival_timestamp = departure_time.timestamp() + travel_hours * 3600 * route_fraction
        estimated_arrival = datetime.fromtimestamp(arrival_timestamp, timezone.utc)
        weather = get_weather_at(latitude, longitude, estimated_arrival)
        weather["risk"] = classify_checkpoint_risk(
            weather["windMph"], weather["rainInHr"], weather["snowInHr"], load_weight
        )
        checkpoints.append({
            "mile": round(distance_along_route, 1),
            "lat": latitude,
            "lon": longitude,
            "eta": estimated_arrival.isoformat(),
            **weather,
        })

    severe_miles = sum(
        next_point["mile"] - point["mile"]
        for point, next_point in zip(checkpoints, checkpoints[1:])
        if RISK_SCORES[point["risk"]] >= RISK_SCORES["Severe"]
    )
    high_risk_miles = sum(
        next_point["mile"] - point["mile"]
        for point, next_point in zip(checkpoints, checkpoints[1:])
        if RISK_SCORES[point["risk"]] == RISK_SCORES["High"]
    )
    average_risk = sum(RISK_SCORES[point["risk"]] for point in checkpoints) / len(checkpoints)
    arrival_time = datetime.fromtimestamp(
        departure_time.timestamp() + travel_hours * 3600, timezone.utc
    )

    return {
        "id": f"{route_data.get('weight_name', 'route')}{route_data.get('weight', 0)}",
        "distanceMiles": round(distance_miles, 1),
        "durationHours": round(travel_hours, 1),
        "arrival": arrival_time.isoformat(),
        "geometry": route_coordinates,
        "checkpoints": checkpoints,
        "severeMiles": round(severe_miles, 1),
        "highMiles": round(high_risk_miles, 1),
        "averageRisk": round(average_risk, 2),
        "summary": f"{distance_miles:.0f} miles · {travel_hours:.1f} hr · {origin['label']} to {destination['label']}",
    }


@require_POST
def plan_route(request):
    try:
        request_data = json.loads(request.body)
        origin = geocode_location(request_data["origin"])
        destination = geocode_location(request_data["destination"])
        load_weight = float(request_data["loadWeight"])
        checkpoint_spacing = int(request_data.get("intervalMiles", 25))
        if load_weight < 0 or checkpoint_spacing not in (10, 25, 50):
            return JsonResponse(
                {"error": "Load must be non-negative and interval must be 10, 25, or 50 miles."},
                status=400,
            )

        departure_time = parse_departure(request_data["departure"])
        route_url = (
            f"{ROUTING_API_URL}{origin['lon']},{origin['lat']};"
            f"{destination['lon']},{destination['lat']}"
        )
        response = requests.get(
            route_url,
            params={"overview": "full", "geometries": "geojson", "alternatives": "3", "steps": "false"},
            timeout=30,
        )
        response.raise_for_status()
        routing_result = response.json()
        if routing_result.get("code") != "Ok" or not routing_result.get("routes"):
            return JsonResponse({"error": "No drivable routes found."}, status=422)

        route_summaries = [
            build_route_summary(
                route_data, origin, destination, departure_time, load_weight, checkpoint_spacing
            )
            for route_data in routing_result["routes"][:3]
        ]
        route_summaries.sort(key=lambda route: (
            route["severeMiles"],
            route["highMiles"],
            route["averageRisk"],
            route["durationHours"],
        ))
        for route_index, route in enumerate(route_summaries):
            route["recommended"] = route_index == 0

        return JsonResponse({
            "origin": origin,
            "destination": destination,
            "routes": route_summaries,
            "recommendedRouteId": route_summaries[0]["id"],
            "forecastHours": 48,
        })
    except requests.RequestException as error:
        return JsonResponse(
            {"error": f"A routing, geocoding, or weather service is unavailable: {error}"},
            status=502,
        )
    except (KeyError, ValueError, TypeError, json.JSONDecodeError) as error:
        return JsonResponse({"error": str(error) or "Invalid request."}, status=400)
