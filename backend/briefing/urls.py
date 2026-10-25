from django.urls import path

from briefing.views import create_briefing

app_name = "briefing"

urlpatterns = [
    path("", create_briefing, name="create-briefing"),
]
