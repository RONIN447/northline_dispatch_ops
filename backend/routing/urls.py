
from django.urls import path  # pyright: ignore[reportMissingModuleSource]
from .views import plan_route

urlpatterns = [path("plan/", plan_route, name="plan-route")]
