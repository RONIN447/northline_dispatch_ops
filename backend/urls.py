from django.urls import include, path # pyright: ignore[reportMissingModuleSource]
from django.views.generic.base import RedirectView # pyright: ignore[reportMissingModuleSource]

urlpatterns = [
    path("", RedirectView.as_view(url="http://127.0.0.1:5173/"), name="root-redirect"),
    path("api/", include("routing.urls")),
]
