"""Route planning and checkpoint weather scoring for Wayfinder."""

import json
import math
import os
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
    from django.views.decorators.http import require_GET, require_POST  # type: ignore[import-not-found]
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

    def require_GET(view_func):
        """Fallback decorator used when Django is unavailable."""

        def _wrapped(*args, **kwargs):
            raise RuntimeError(
                "Django is not installed. Install project dependencies before using the routing API."
            )

        return _wrapped

ROUTING_API_URL = "https://router.project-osrm.org/route/v1/driving/"
WEATHERAPI_SEARCH_URL = "https://api.weatherapi.com/v1/search.json"
WEATHERAPI_FORECAST_URL = "https://api.weatherapi.com/v1/forecast.json"

# Every checkpoint carries a risk grade. This dictionary makes it easy to compare
# and rank routes by severity in a predictable, operationally meaningful order.
RISK_SCORES = {"Low": 0, "Moderate": 1, "High": 2, "Severe": 3, "No Travel": 4}
MILES_PER_KILOMETER = 0.621371
WEATHERAPI_FORECAST_DAYS = 3
WEATHERAPI_MAX_PARALLEL_REQUESTS = 4


class WeatherDataUnavailable(Exception):
    """Raised when a checkpoint cannot be matched to a real forecast value."""


class WeatherProviderConfigurationError(Exception):
    """Raised when WeatherAPI is not configured correctly."""


class RouteAlternativesUnavailable(Exception):
    """Raised when the routing provider cannot produce three distinct routes."""


def health_check(request):
    return JsonResponse({"status": "ok"})


@require_GET
def location_suggestions(request):
    try:
        matches = search_locations(request.GET.get("q", ""))
        return JsonResponse({
            "results": [
                {
                    "id": f"{match['lat']},{match['lon']}",
                    "name": match["name"],
                    "admin1": match["region"],
                    "country": match["country"],
                }
                for match in matches
            ]
        })
    except requests.RequestException as error:
        return _provider_error_response(error, "location search")
    except WeatherProviderConfigurationError as error:
        return JsonResponse({"error": str(error)}, status=503)
    except WeatherDataUnavailable as error:
        return JsonResponse({"error": str(error)}, status=502)
    except (KeyError, TypeError, ValueError) as error:
        return JsonResponse({"error": str(error) or "Invalid location search."}, status=400)


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


def weather_api_key():
    key = os.getenv("WEATHERAPI_KEY", "").strip()
    if not key:
        raise WeatherProviderConfigurationError(
            "Weather forecasts and city suggestions require WEATHERAPI_KEY to be configured."
        )
    return key


def _provider_error_response(error, service_name):
    response = getattr(error, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code == 429:
        return JsonResponse(
            {"error": "WeatherAPI is rate-limited right now. Please wait a moment and try again."},
            status=429,
        )
    if status_code in (401, 403):
        return JsonResponse(
            {"error": "WeatherAPI rejected its API key. Check the server's WEATHERAPI_KEY setting."},
            status=502,
        )
    return JsonResponse(
        {"error": f"The {service_name} provider is unavailable"
         + (f" (HTTP {status_code})." if status_code else ".")},
        status=502,
    )


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
def _search_locations_cached(query):
    response = _perform_api_request(
        WEATHERAPI_SEARCH_URL,
        params={"key": weather_api_key(), "q": query},
        timeout=20,
    )
    matches = response.json()
    if not isinstance(matches, list):
        raise WeatherDataUnavailable("The location provider returned an unexpected response.")
    return [
        {
            "lat": match["lat"],
            "lon": match["lon"],
            "name": match.get("name", ""),
            "region": match.get("region", ""),
            "country": match.get("country", ""),
            "timezone": match.get("tz_id", "UTC"),
        }
        for match in matches
    ]


def search_locations(query):
    cleaned_query = query.strip()
    if len(cleaned_query) < 2:
        return []
    if len(cleaned_query) > 100:
        raise ValueError("Location search must be 100 characters or fewer.")
    return _search_locations_cached(cleaned_query)


def _display_location_name(match):
    return {
        "label": ", ".join(
            part for part in (match.get("name"), match.get("region"), match.get("country")) if part
        ),
        "lat": match["lat"],
        "lon": match["lon"],
        "timezone": match.get("timezone", "UTC"),
    }


def geocode_location(location_name):
    matches = search_locations(location_name)
    if not matches:
        raise ValueError(f"Could not find location: {location_name}")
    return _display_location_name(matches[0])


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


def _get_weather_forecast(latitude, longitude):
    response = _perform_api_request(
        WEATHERAPI_FORECAST_URL,
        params={
            "key": weather_api_key(),
            "q": f"{latitude:.6f},{longitude:.6f}",
            "days": WEATHERAPI_FORECAST_DAYS,
            "aqi": "no",
            "alerts": "no",
        },
        timeout=20,
    )
    forecast_days = response.json().get("forecast", {}).get("forecastday", [])
    return [
        hour
        for forecast_day in forecast_days
        for hour in forecast_day.get("hour", [])
    ]


def get_weather_at(latitude, longitude, arrival_time):
    return parse_weather_forecast(
        _get_weather_forecast(latitude, longitude),
        arrival_time,
    )


def parse_weather_forecast(hourly_forecast, arrival_time):
    if not hourly_forecast:
        raise WeatherDataUnavailable("The weather provider returned no hourly forecast.")

    arrival_utc = arrival_time.astimezone(timezone.utc)
    valid_hours = []
    for hour in hourly_forecast:
        try:
            forecast_epoch = int(hour["time_epoch"])
        except (KeyError, TypeError, ValueError):
            continue
        valid_hours.append((forecast_epoch, hour))
    if not valid_hours:
        raise WeatherDataUnavailable("The weather provider returned an invalid forecast time.")

    forecast_epoch, selected_hour = min(
        valid_hours,
        key=lambda item: abs(item[0] - arrival_utc.timestamp()),
    )
    forecast_time = datetime.fromtimestamp(forecast_epoch, timezone.utc)
    if abs((forecast_time - arrival_utc).total_seconds()) > 3600:
        raise WeatherDataUnavailable(
            "The requested arrival time is outside WeatherAPI's available forecast."
        )

    def forecast_value(field_name, label):
        value = selected_hour.get(field_name)
        if value is None:
            raise WeatherDataUnavailable(
                f"The weather provider returned no {label} data for a checkpoint."
            )
        try:
            numeric_value = float(value)
        except (TypeError, ValueError, OverflowError) as error:
            raise WeatherDataUnavailable(
                f"The weather provider returned invalid {label} data for a checkpoint."
            ) from error
        if not math.isfinite(numeric_value) or numeric_value < 0:
            raise WeatherDataUnavailable(
                f"The weather provider returned invalid {label} data for a checkpoint."
            )
        return numeric_value

    temperature_f = None
    if selected_hour.get("temp_f") is not None:
        try:
            temperature_f = float(selected_hour["temp_f"])
        except (TypeError, ValueError, OverflowError) as error:
            raise WeatherDataUnavailable(
                "The weather provider returned invalid temperature data for a checkpoint."
            ) from error
        if not math.isfinite(temperature_f):
            raise WeatherDataUnavailable(
                "The weather provider returned invalid temperature data for a checkpoint."
            )

    return {
        "windMph": forecast_value("wind_mph", "wind"),
        "rainInHr": forecast_value("precip_in", "precipitation"),
        "snowInHr": forecast_value("snow_cm", "snowfall") * 0.3937007874,
        "temperatureF": temperature_f,
        "forecastHour": forecast_time.isoformat(),
    }


def get_weather_for_locations(checkpoint_locations):
    def fetch_weather(location):
        _, latitude, longitude, arrival = location
        return get_weather_at(latitude, longitude, arrival)

    with ThreadPoolExecutor(max_workers=WEATHERAPI_MAX_PARALLEL_REQUESTS) as executor:
        return list(executor.map(fetch_weather, checkpoint_locations))


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
        return _provider_error_response(error, "routing or weather")
    except WeatherProviderConfigurationError as error:
        return JsonResponse({"error": str(error)}, status=503)
    except WeatherDataUnavailable as error:
        return JsonResponse({"error": str(error)}, status=502)
    except RouteAlternativesUnavailable as error:
        return JsonResponse({"error": str(error)}, status=422)
    except (KeyError, ValueError, TypeError, json.JSONDecodeError) as error:
        return JsonResponse({"error": str(error) or "Invalid request."}, status=400)
