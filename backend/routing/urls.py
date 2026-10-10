
from django.urls import path  # pyright: ignore[reportMissingModuleSource]
from .views import health_check, location_suggestions, plan_route

urlpatterns = [
    path("health/", health_check, name="health-check"),
    path("locations/", location_suggestions, name="location-suggestions"),
    path("plan/", plan_route, name="plan-route"),
]
