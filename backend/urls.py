import os

from django.urls import include, path  # pyright: ignore[reportMissingModuleSource]
from django.views.generic.base import RedirectView  # pyright: ignore[reportMissingModuleSource]

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://127.0.0.1:5173")

urlpatterns = [
    path("", RedirectView.as_view(url=FRONTEND_URL.rstrip("/") + "/"), name="root-redirect"),
    path("api/", include("routing.urls")),
]
