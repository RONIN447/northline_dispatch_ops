"""HTTP endpoint for generating guarded dispatch briefings."""

import json
import ipaddress
import logging
import math
import threading
import time
from collections import OrderedDict, deque
from dataclasses import asdict
from datetime import datetime, timezone
from uuid import uuid4

from django.http import JsonResponse
from django.views.decorators.http import require_POST

from evals.checks import validate_briefing
from briefing.providers import ProviderConfigurationError, ProviderRequestError
from briefing.service import BriefingGenerationError, generate_briefing
from briefing.validator import BriefingValidationError, enforce
from routing.risk_levels import RISK_LEVELS

MAX_REQUEST_BYTES = 1024 * 1024
RATE_LIMIT_REQUESTS = 10
RATE_LIMIT_WINDOW_SECONDS = 60
DAILY_REQUEST_LIMIT = 500
DAILY_REQUEST_LIMIT = 1000
MAX_TRACKED_CLIENTS = 10000
_request_times = OrderedDict()
_rate_limit_lock = threading.Lock()
_daily_request_date = None
_daily_request_count = 0
_logger = logging.getLogger(__name__)


@require_POST
def create_briefing(request):
    request_id = uuid4().hex
    if len(request.body) > MAX_REQUEST_BYTES:
        return _error_response("Request body exceeds the 1 MB limit.", 413, request_id)

    client_ip = _client_ip(request)
    if not _allow_request(client_ip):
        return _error_response(
            "Briefing request limit reached. Please wait and try again.", 429, request_id
        )

    try:
        plan = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _error_response("Request body must contain valid JSON.", 400, request_id)

    validation_error = _validate_plan_shape(plan)
    if validation_error:
        return _error_response(validation_error, 400, request_id)
    if not _consume_daily_request():
        return _error_response(
            "Daily briefing request limit reached. Please try again tomorrow.",
            429,
            request_id,
        )

    try:
        briefing, metadata = generate_briefing(plan)
        final_briefing, interventions, fallback_used = enforce(plan, briefing)
    except ProviderConfigurationError as error:
        _log_safe_exception(request_id, error)
        return _error_response(
            "Briefing generation is not configured on this server.", 503, request_id
        )
    except ProviderRequestError as error:
        _log_safe_exception(request_id, error)
        return _error_response(
            "The briefing provider is temporarily unavailable.", 502, request_id
        )
    except BriefingGenerationError as error:
        _log_safe_exception(request_id, error)
        return _error_response(
            "The briefing provider returned invalid output after retrying.", 502, request_id
        )
    except BriefingValidationError as error:
        _log_safe_exception(request_id, error)
        return _error_response(
            "The route plan could not be safely validated for briefing.", 400, request_id
        )

    check_errors = validate_briefing(final_briefing, plan)
    if check_errors:
        _logger.error(
            "Briefing safety validation failed request_id=%s check_count=%d",
            request_id,
            len(check_errors),
        )
        return _error_response(
            "The generated briefing did not pass safety validation.", 502, request_id
        )

    return JsonResponse(
        {
            "briefing": final_briefing.model_dump(mode="json"),
            "interventions": [asdict(item) for item in interventions],
            "fallback_used": fallback_used,
            "metadata": asdict(metadata),
            "request_id": request_id,
        }
    )


def _error_response(message, status, request_id):
    return JsonResponse({"error": message, "request_id": request_id}, status=status)


def _log_safe_exception(request_id, error):
    _logger.warning(
        "Briefing request failed request_id=%s exception_type=%s",
        request_id,
        type(error).__name__,
    )


def _client_ip(request):
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    forwarded_addresses = [part.strip() for part in forwarded_for.split(",") if part.strip()]
    if forwarded_addresses:
        candidate = forwarded_addresses[-1]
        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            pass
    return request.META.get("REMOTE_ADDR", "unknown")


def _allow_request(client_ip):
    now = time.monotonic()
    cutoff = now - RATE_LIMIT_WINDOW_SECONDS
    with _rate_limit_lock:
        request_queue = _request_times.get(client_ip)
        if request_queue is None:
            if len(_request_times) >= MAX_TRACKED_CLIENTS:
                _request_times.popitem(last=False)
            request_queue = deque()
            _request_times[client_ip] = request_queue
        else:
            _request_times.move_to_end(client_ip)
        while request_queue and request_queue[0] <= cutoff:
            request_queue.popleft()
        if len(request_queue) >= RATE_LIMIT_REQUESTS:
            return False
        request_queue.append(now)
        return True


def _consume_daily_request():
    global _daily_request_date, _daily_request_count
    today = datetime.now(timezone.utc).date()
    with _rate_limit_lock:
        if _daily_request_date != today:
            _daily_request_date = today
            _daily_request_count = 0
        if _daily_request_count >= DAILY_REQUEST_LIMIT:
            return False
        _daily_request_count += 1
        return True


def _validate_plan_shape(plan):
    if not isinstance(plan, dict):
        return "Request JSON must be an object."
    routes = plan.get("routes")
    recommended_route_id = plan.get("recommendedRouteId")
    if not isinstance(routes, list) or not routes:
        return "Route plan must include a non-empty routes list."
    if not isinstance(recommended_route_id, str):
        return "Route plan must include recommendedRouteId."
    if not isinstance(plan.get("origin"), dict) or not isinstance(
        plan.get("destination"), dict
    ):
        return "Route plan must include origin and destination objects."
    for endpoint_name in ("origin", "destination"):
        endpoint = plan[endpoint_name]
        if not isinstance(endpoint.get("label"), str) or not endpoint["label"].strip():
            return "{} must include a non-empty label.".format(endpoint_name.capitalize())
        for field in ("lat", "lon"):
            value = endpoint.get(field)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                return "{} must include finite {}.".format(endpoint_name.capitalize(), field)
    route_ids = set()
    for route in routes:
        if not isinstance(route, dict) or not isinstance(route.get("id"), str):
            return "Each route must include a string id."
        route_id = route["id"]
        if not route_id or route_id in route_ids:
            return "Route ids must be non-empty and unique."
        route_ids.add(route_id)
        if not isinstance(route.get("checkpoints"), list):
            return "Each route must include a checkpoints list."
        for checkpoint in route["checkpoints"]:
            if not isinstance(checkpoint, dict):
                return "Each checkpoint must be an object."
            if checkpoint.get("risk") not in RISK_LEVELS:
                return "Each checkpoint must include a canonical risk level."
        for field in (
            "distanceMiles",
            "durationHours",
            "severeMiles",
            "highMiles",
            "noTravelMiles",
        ):
            value = route.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return "Each route must include valid {}.".format(field)
            if not math.isfinite(value):
                return "Each route must include finite {}.".format(field)
        for field in ("averageRisk",):
            value = route.get(field)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                return "Each route must include finite {}.".format(field)
        if not isinstance(route.get("arrival"), str) or not isinstance(
            route.get("summary"), str
        ):
            return "Each route must include string arrival and summary fields."
        for checkpoint in route["checkpoints"]:
            if not isinstance(checkpoint.get("eta"), str):
                return "Each checkpoint must include a string eta."
            for field in (
                "mile",
                "windMph",
                "rainInHr",
                "snowInHr",
                "temperatureF",
            ):
                value = checkpoint.get(field)
                if value is not None and (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                ):
                    return "Each checkpoint must include finite {}.".format(field)
    if recommended_route_id not in route_ids:
        return "recommendedRouteId must match a route in routes."
    return None
