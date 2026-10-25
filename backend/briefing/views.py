"""HTTP endpoint for generating guarded dispatch briefings."""

import json
import math
import threading
import time
from collections import OrderedDict, deque
from dataclasses import asdict

from django.http import JsonResponse
from django.views.decorators.http import require_POST

from evals.checks import validate_briefing
from briefing.providers import ProviderRequestError
from briefing.service import BriefingGenerationError, generate_briefing
from briefing.validator import BriefingValidationError, enforce
from routing.risk_levels import RISK_LEVELS

MAX_REQUEST_BYTES = 1024 * 1024
RATE_LIMIT_REQUESTS = 10
RATE_LIMIT_WINDOW_SECONDS = 60
MAX_TRACKED_CLIENTS = 10000
_request_times = OrderedDict()
_rate_limit_lock = threading.Lock()


@require_POST
def create_briefing(request):
    if len(request.body) > MAX_REQUEST_BYTES:
        return JsonResponse({"error": "Request body exceeds the 1 MB limit."}, status=413)

    client_ip = request.META.get("REMOTE_ADDR", "unknown")
    if not _allow_request(client_ip):
        return JsonResponse(
            {"error": "Briefing request limit reached. Please wait and try again."},
            status=429,
        )

    try:
        plan = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Request body must contain valid JSON."}, status=400)

    validation_error = _validate_plan_shape(plan)
    if validation_error:
        return JsonResponse({"error": validation_error}, status=400)

    try:
        briefing, metadata = generate_briefing(plan)
        final_briefing, interventions, fallback_used = enforce(plan, briefing)
    except ProviderRequestError:
        return JsonResponse(
            {"error": "The briefing provider is temporarily unavailable."},
            status=502,
        )
    except BriefingGenerationError:
        return JsonResponse(
            {"error": "The briefing provider returned invalid output after retrying."},
            status=502,
        )
    except BriefingValidationError:
        return JsonResponse(
            {"error": "The route plan could not be safely validated for briefing."},
            status=400,
        )

    check_errors = validate_briefing(final_briefing, plan)
    if check_errors:
        return JsonResponse(
            {"error": "The generated briefing did not pass safety validation."},
            status=502,
        )

    return JsonResponse(
        {
            "briefing": final_briefing.model_dump(mode="json"),
            "interventions": [asdict(item) for item in interventions],
            "fallback_used": fallback_used,
            "metadata": asdict(metadata),
        }
    )


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
        for checkpoint in route["checkpoints"]:
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
