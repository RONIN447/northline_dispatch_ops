"""Route planning and checkpoint weather scoring for Wayfinder."""

import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from functools import lru_cache

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

# Every checkpoint carries a risk grade. This dictionary makes it easy to compare
# and rank routes by severity in a predictable, operationally meaningful order.
RISK_SCORES = {"Low": 0, "Moderate": 1, "High": 2, "Severe": 3, "No Travel": 4}
MILES_PER_KILOMETER = 0.621371
WEATHER_HOURLY_FIELDS = "rain,snowfall,wind_speed_10m"


class WeatherDataUnavailable(Exception):
    """Raised when a checkpoint cannot be matched to a real forecast value."""


class RouteAlternativesUnavailable(Exception):
    """Raised when the routing provider cannot produce three distinct routes."""


def health_check(request):
    return JsonResponse({"status": "ok"})


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


def parse_load_weight(value):
    try:
        load_weight = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("Load weight must be a valid number.") from error
    if not math.isfinite(load_weight) or load_weight < 0:
        raise ValueError("Load weight must be a finite, non-negative number.")
    return load_weight


def parse_checkpoint_spacing(value):
    try:
        spacing = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("Checkpoint interval must be 10, 25, or 50 miles.") from error
    if not math.isfinite(spacing) or not spacing.is_integer() or int(spacing) not in (10, 25, 50):
        raise ValueError("Checkpoint interval must be 10, 25, or 50 miles.")
    return int(spacing)


def parse_location_name(value, field_name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required.")
    return value.strip()


def _sleep_before_retry(response=None, attempt=0):
    retry_after = None
    if response is not None and getattr(response, "headers", None):
        retry_after_value = response.headers.get("Retry-After")
        if retry_after_value is not None:
            try:
                retry_after = max(1, float(retry_after_value))
            except (TypeError, ValueError):
                retry_after = None
    delay_seconds = retry_after if retry_after is not None else min(5.0, 0.75 * (2 ** attempt))
    time.sleep(delay_seconds)
    return delay_seconds


def _perform_api_request(url, params=None, timeout=20, max_retries=3):
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            response = requests.get(url, params=params, timeout=timeout)
            status_code = getattr(response, "status_code", None)
            if status_code == 429 and attempt < max_retries:
                _sleep_before_retry(response, attempt)
                continue
            response.raise_for_status()
            return response
        except requests.RequestException as error:
            last_error = error
            response = getattr(error, "response", None)
            if response is not None and getattr(response, "status_code", None) == 429 and attempt < max_retries:
                _sleep_before_retry(response, attempt)
                continue
            raise
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Request to {url} failed without a response.")


@lru_cache(maxsize=256)
def _geocode_cached(location_name):
    response = _perform_api_request(
        GEOCODING_API_URL,
        params={"name": location_name, "count": 1, "language": "en", "format": "json"},
        timeout=20,
    )
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


def geocode_location(location_name):
    return _geocode_cached(location_name.strip())


def classify_checkpoint_risk(wind_mph, rain_inches_per_hour, snow_inches_per_hour, load_weight):
    """Return the highest applicable weather category after load adjustments."""
    # Safety rule: extreme wind is a hard stop for the operation, and heavy cargo
    # makes moderate wind more dangerous because the vehicle is less stable.
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


@lru_cache(maxsize=512)
def _weather_for_point_cached(latitude, longitude, arrival_time_iso):
    response = _perform_api_request(
        WEATHER_API_URL,
        params={
            "latitude": latitude,
            "longitude": longitude,
            "hourly": "temperature_2m,precipitation,rain,snowfall,wind_speed_10m",
            "forecast_days": 7,
            "timezone": "UTC",
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
        },
        timeout=20,
    )
    arrival_time = datetime.fromisoformat(arrival_time_iso)
    return parse_weather_forecast(response.json().get("hourly", {}), arrival_time)


def get_weather_at(latitude, longitude, arrival_time):
    arrival_time_iso = arrival_time.astimezone(timezone.utc).isoformat()
    return _weather_for_point_cached(latitude, longitude, arrival_time_iso)


def parse_weather_forecast(hourly_forecast, arrival_time):
    forecast_times = hourly_forecast.get("time", [])
    if not forecast_times:
        raise WeatherDataUnavailable("The weather provider returned no hourly forecast.")

    arrival_utc = arrival_time.astimezone(timezone.utc)
    forecast_index = min(
        range(len(forecast_times)),
        key=lambda index: abs(
            datetime.fromisoformat(forecast_times[index]).replace(tzinfo=timezone.utc)
            - arrival_utc
        ).total_seconds(),
    )
    forecast_time = datetime.fromisoformat(forecast_times[forecast_index]).replace(
        tzinfo=timezone.utc
    )
    if abs((forecast_time - arrival_utc).total_seconds()) > 3600:
        raise WeatherDataUnavailable(
            "The requested arrival time is outside the available weather forecast."
        )

    def forecast_value(field_name):
        values = hourly_forecast.get(field_name, [])
        if forecast_index >= len(values) or values[forecast_index] is None:
            raise WeatherDataUnavailable(
                f"The weather provider returned no {field_name} data for a checkpoint."
            )
        value = float(values[forecast_index])
        if not math.isfinite(value) or value < 0:
            raise WeatherDataUnavailable(
                f"The weather provider returned invalid {field_name} data for a checkpoint."
            )
        return value

    temperatures = hourly_forecast.get("temperature_2m", [])
    temperature_f = None
    if forecast_index < len(temperatures) and temperatures[forecast_index] is not None:
        # Temperatures may legitimately be below 0 C; unlike precipitation and wind,
        # they must not go through the non-negative weather-value validator above.
        temperature_c = float(temperatures[forecast_index])
        if not math.isfinite(temperature_c):
            raise WeatherDataUnavailable(
                "The weather provider returned invalid temperature data for a checkpoint."
            )
        temperature_f = temperature_c * 9 / 5 + 32

    return {
        "windMph": forecast_value("wind_speed_10m"),
        "rainInHr": forecast_value("rain"),
        "snowInHr": forecast_value("snowfall"),
        "temperatureF": temperature_f,
        "forecastHour": forecast_times[forecast_index],
    }


def get_weather_for_locations(checkpoint_locations):
    weather_results = []
    batch_size = 50
    for batch_start in range(0, len(checkpoint_locations), batch_size):
        batch = checkpoint_locations[batch_start:batch_start + batch_size]
        response = _perform_api_request(
            WEATHER_API_URL,
            params={
                "latitude": ",".join(f"{latitude:.6f}" for _, latitude, _, _ in batch),
                "longitude": ",".join(f"{longitude:.6f}" for _, _, longitude, _ in batch),
                "hourly": WEATHER_HOURLY_FIELDS,
                "forecast_days": forecast_days_for_locations(batch),
                "timezone": "UTC",
                "wind_speed_unit": "mph",
                "precipitation_unit": "inch",
            },
            timeout=20,
        )
        forecast_data = response.json()
        forecasts = forecast_data if isinstance(forecast_data, list) else [forecast_data]
        if len(forecasts) != len(batch):
            raise WeatherDataUnavailable(
                "The weather provider returned an unexpected number of checkpoint forecasts."
            )
        weather_results.extend(
            parse_weather_forecast(forecast.get("hourly", {}), arrival)
            for forecast, (_, _, _, arrival) in zip(forecasts, batch)
        )
    return weather_results


def forecast_days_for_locations(checkpoint_locations):
    latest_arrival = max(location[3] for location in checkpoint_locations)
    hours_until_arrival = max(
        0,
        (latest_arrival - datetime.now(timezone.utc)).total_seconds() / 3600,
    )
    return min(7, max(1, math.ceil(hours_until_arrival / 24) + 1))


# The map needs a coordinate at an exact route position, not just the start or end.
# This helper estimates the point along the polyline where a checkpoint should appear.
def coordinate_at_route_fraction(route_coordinates, route_fraction):
    """Find the coordinate at a fraction of the route's length."""
    if not route_coordinates:
        raise ValueError("The routing provider returned an empty route geometry.")
    if not 0 <= route_fraction <= 1:
        raise ValueError("Route fraction must be between 0 and 1.")
    if len(route_coordinates) == 1:
        return route_coordinates[0]

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
        segment_lengths_km.append(2 * 6371 * math.asin(math.sqrt(min(1, haversine))))

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


def offset_route_waypoints(route_coordinates, offset_km):
    """Create routing waypoints on either side of a route at three points."""
    waypoints = []
    for route_fraction in (0.35, 0.5, 0.65):
        longitude, latitude = coordinate_at_route_fraction(
            route_coordinates, route_fraction
        )
        before = coordinate_at_route_fraction(
            route_coordinates, max(0, route_fraction - 0.02)
        )
        after = coordinate_at_route_fraction(
            route_coordinates, min(1, route_fraction + 0.02)
        )
        longitude_scale = 111.32 * max(0.01, math.cos(math.radians(latitude)))
        east = (after[0] - before[0]) * longitude_scale
        north = (after[1] - before[1]) * 110.574
        tangent_length = math.hypot(east, north)
        if tangent_length == 0:
            continue

        for direction in (-1, 1):
            offset_east = direction * -north / tangent_length * offset_km
            offset_north = direction * east / tangent_length * offset_km
            waypoints.append((
                max(-85, min(85, latitude + offset_north / 110.574)),
                max(-180, min(180, longitude + offset_east / longitude_scale)),
            ))
    return waypoints


def route_samples(route_data):
    coordinates = route_data.get("geometry", {}).get("coordinates", [])
    if not coordinates:
        return []
    return [
        coordinate_at_route_fraction(coordinates, fraction)
        for fraction in (0.25, 0.5, 0.75)
    ]


def routes_are_distinct(first_route, second_route):
    first_samples = route_samples(first_route)
    second_samples = route_samples(second_route)
    if len(first_samples) != 3 or len(second_samples) != 3:
        return False

    for first, second in zip(first_samples, second_samples):
        longitude_delta = math.radians(second[0] - first[0])
        latitude_delta = math.radians(second[1] - first[1])
        haversine = (
            math.sin(latitude_delta / 2) ** 2
            + math.cos(math.radians(first[1]))
            * math.cos(math.radians(second[1]))
            * math.sin(longitude_delta / 2) ** 2
        )
        separation_km = 2 * 6371 * math.asin(math.sqrt(min(1, haversine)))
        if separation_km >= 10:
            return True
    return False


def fetch_route_options(origin, destination):
    """Ask OSRM for three routes, using distinct via-point routes as a fallback."""
    origin_coordinate = f"{origin['lon']},{origin['lat']}"
    destination_coordinate = f"{destination['lon']},{destination['lat']}"
    route_url = f"{ROUTING_API_URL}{origin_coordinate};{destination_coordinate}"
    response = _perform_api_request(
        route_url,
        params={
            "overview": "full",
            "geometries": "geojson",
            "alternatives": "3",
            "steps": "false",
        },
        timeout=30,
    )
    routing_result = response.json()
    if routing_result.get("code") != "Ok" or not routing_result.get("routes"):
        return []

    routes = list(routing_result["routes"][:3])
    if len(routes) == 3:
        return routes

    base_geometry = routes[0].get("geometry", {}).get("coordinates", [])
    if not base_geometry:
        raise RouteAlternativesUnavailable(
            "The routing provider returned route data without usable geometry."
        )

    for offset_km in (30, 60):
        waypoints = offset_route_waypoints(base_geometry, offset_km)
        for pair_start in range(0, len(waypoints), 2):
            waypoint_requests = [
                f"{ROUTING_API_URL}{origin_coordinate};{longitude},{latitude};"
                f"{destination_coordinate}"
                for latitude, longitude in waypoints[pair_start:pair_start + 2]
            ]
            if not waypoint_requests:
                continue
            with ThreadPoolExecutor(max_workers=len(waypoint_requests)) as executor:
                futures = [
                    executor.submit(
                        _perform_api_request,
                        waypoint_url,
                        params={
                            "overview": "full",
                            "geometries": "geojson",
                            "alternatives": "false",
                            "steps": "false",
                        },
                        timeout=30,
                    )
                    for waypoint_url in waypoint_requests
                ]
                for future in as_completed(futures):
                    try:
                        candidate_response = future.result()
                        candidate_result = candidate_response.json()
                    except requests.RequestException:
                        continue

                    if candidate_result.get("code") != "Ok":
                        continue
                    for candidate in candidate_result.get("routes", []):
                        if all(routes_are_distinct(candidate, route) for route in routes):
                            routes.append(candidate)
                            break
                    if len(routes) == 3:
                        break

            if len(routes) == 3:
                return routes

    raise RouteAlternativesUnavailable(
        "The routing provider could not find three distinct drivable routes for this trip. "
        "Try a different origin or destination."
    )


def build_checkpoint_locations(route_data, departure_time, checkpoint_spacing):
    route_coordinates = route_data["geometry"]["coordinates"]
    distance_miles = route_data["distance"] / 1000 * MILES_PER_KILOMETER
    travel_hours = route_data["duration"] / 3600
    checkpoint_count = max(1, math.ceil(distance_miles / checkpoint_spacing))
    checkpoint_locations = []

    # Generate evenly spaced checkpoints and their estimated arrival times.
    for checkpoint_index in range(checkpoint_count + 1):
        distance_along_route = (
            min(distance_miles, checkpoint_index * checkpoint_spacing)
            if checkpoint_index < checkpoint_count else distance_miles
        )
        route_fraction = distance_along_route / distance_miles if distance_miles else 0
        longitude, latitude = coordinate_at_route_fraction(route_coordinates, route_fraction)
        arrival_timestamp = departure_time.timestamp() + travel_hours * 3600 * route_fraction
        estimated_arrival = datetime.fromtimestamp(arrival_timestamp, timezone.utc)
        checkpoint_locations.append((distance_along_route, latitude, longitude, estimated_arrival))

    return checkpoint_locations


def build_route_summary(
    route_data,
    origin,
    destination,
    departure_time,
    load_weight,
    checkpoint_spacing,
    route_index,
    weather_results=None,
):
    route_coordinates = route_data["geometry"]["coordinates"]
    distance_miles = route_data["distance"] / 1000 * MILES_PER_KILOMETER
    travel_hours = route_data["duration"] / 3600
    checkpoint_locations = build_checkpoint_locations(
        route_data, departure_time, checkpoint_spacing
    )
    checkpoints = []

    if weather_results is None:
        weather_results = get_weather_for_locations(checkpoint_locations)
    if len(weather_results) != len(checkpoint_locations):
        raise WeatherDataUnavailable(
            "The weather provider returned an unexpected number of checkpoint forecasts."
        )

    for (distance_along_route, latitude, longitude, estimated_arrival), weather in zip(
        checkpoint_locations, weather_results
    ):
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

    no_travel_miles = sum(
        next_point["mile"] - point["mile"]
        for point, next_point in zip(checkpoints, checkpoints[1:])
        if point["risk"] == "No Travel"
    )
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
    covered_miles = sum(
        next_point["mile"] - point["mile"]
        for point, next_point in zip(checkpoints, checkpoints[1:])
    )
    average_risk = (
        sum(
            RISK_SCORES[point["risk"]] * (next_point["mile"] - point["mile"])
            for point, next_point in zip(checkpoints, checkpoints[1:])
        ) / covered_miles
        if covered_miles
        else RISK_SCORES[checkpoints[0]["risk"]]
    )
    arrival_time = datetime.fromtimestamp(
        departure_time.timestamp() + travel_hours * 3600, timezone.utc
    )

    return {
        "id": f"route-{route_index}-{route_data.get('weight_name', 'option')}",
        "distanceMiles": round(distance_miles, 1),
        "durationHours": round(travel_hours, 1),
        "arrival": arrival_time.isoformat(),
        "geometry": route_coordinates,
        "checkpoints": checkpoints,
        "severeMiles": round(severe_miles, 1),
        "highMiles": round(high_risk_miles, 1),
        "noTravelMiles": round(no_travel_miles, 1),
        "averageRisk": round(average_risk, 2),
        "summary": f"{distance_miles:.0f} miles · {travel_hours:.1f} hr · {origin['label']} to {destination['label']}",
        "rankKey": (severe_miles, high_risk_miles, average_risk, travel_hours),
    }


@require_POST
def plan_route(request):
    try:
        request_data = json.loads(request.body)
        load_weight = parse_load_weight(request_data["loadWeight"])
        checkpoint_spacing = parse_checkpoint_spacing(request_data.get("intervalMiles", 25))
        departure_time = parse_departure(request_data["departure"])
        origin_name = parse_location_name(request_data["origin"], "Origin")
        destination_name = parse_location_name(request_data["destination"], "Destination")
        with ThreadPoolExecutor(max_workers=2) as executor:
            origin_future = executor.submit(geocode_location, origin_name)
            destination_future = executor.submit(geocode_location, destination_name)
            origin = origin_future.result()
            destination = destination_future.result()
        routes = fetch_route_options(origin, destination)
        if not routes:
            return JsonResponse({"error": "No drivable routes found."}, status=422)

        route_checkpoints = [
            build_checkpoint_locations(route, departure_time, checkpoint_spacing)
            for route in routes
        ]
        all_checkpoint_locations = [
            checkpoint
            for checkpoints in route_checkpoints
            for checkpoint in checkpoints
        ]
        all_weather_results = get_weather_for_locations(all_checkpoint_locations)
        route_summaries = []
        weather_offset = 0
        for route_index, (route_data, checkpoint_locations) in enumerate(
            zip(routes, route_checkpoints), start=1
        ):
            weather_end = weather_offset + len(checkpoint_locations)
            route_summaries.append(build_route_summary(
                route_data,
                origin,
                destination,
                departure_time,
                load_weight,
                checkpoint_spacing,
                route_index,
                all_weather_results[weather_offset:weather_end],
            ))
            weather_offset = weather_end
        # Operational ranking is intentionally safety-first: the route with the least
        # severe exposure is selected before duration is considered.
        route_summaries.sort(key=lambda route: route["rankKey"])
        for route_index, route in enumerate(route_summaries):
            route.pop("rankKey")
            route["recommended"] = route_index == 0

        return JsonResponse({
            "origin": origin,
            "destination": destination,
            "routes": route_summaries,
            "recommendedRouteId": route_summaries[0]["id"],
            "forecastHours": 48,
        })
    except requests.RequestException as error:
        response = getattr(error, "response", None)
        if getattr(response, "status_code", None) == 429:
            return JsonResponse(
                {"error": "The weather service is rate-limited right now. Please wait a moment and try again."},
                status=429,
            )
        return JsonResponse(
            {"error": f"A routing, geocoding, or weather service is unavailable: {error}"},
            status=502,
        )
    except WeatherDataUnavailable as error:
        return JsonResponse({"error": str(error)}, status=502)
    except RouteAlternativesUnavailable as error:
        return JsonResponse({"error": str(error)}, status=422)
    except (KeyError, ValueError, TypeError, json.JSONDecodeError) as error:
        return JsonResponse({"error": str(error) or "Invalid request."}, status=400)
