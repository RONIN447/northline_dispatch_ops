"""Small CORS middleware for the separately hosted React frontend."""

import os

from django.http import HttpResponse


class CorsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "OPTIONS" and request.path.startswith("/api/"):
            response = HttpResponse(status=204)
        else:
            response = self.get_response(request)

        allowed_origins = {
            origin.strip().rstrip("/")
            for origin in os.getenv("CORS_ALLOWED_ORIGINS", os.getenv("FRONTEND_URL", "")).split(",")
            if origin.strip()
        }
        if os.getenv("DEBUG", "True").lower() in {"1", "true", "yes", "on"}:
            allowed_origins.update({"http://localhost:5173", "http://127.0.0.1:5173"})

        origin = request.headers.get("Origin", "").rstrip("/")
        if origin in allowed_origins:
            response["Access-Control-Allow-Origin"] = origin
            response["Vary"] = "Origin"
            response["Access-Control-Allow-Methods"] = "POST, OPTIONS"
            response["Access-Control-Allow-Headers"] = "Content-Type, X-CSRFToken"
            response["Access-Control-Max-Age"] = "600"
        return response
