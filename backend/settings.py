import os

SECRET_KEY = os.getenv("SECRET_KEY", "development-only-change-before-deployment")
DEBUG = os.getenv("DEBUG", "True").lower() in {"1", "true", "yes", "on"}
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]

render_hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME")
if render_hostname:
    ALLOWED_HOSTS.append(render_hostname)

if not DEBUG:
    ALLOWED_HOSTS.extend(["localhost", "127.0.0.1"])

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://127.0.0.1:5173")
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CSRF_TRUSTED_ORIGINS", FRONTEND_URL).split(",")
    if origin.strip()
]

ROOT_URLCONF = "urls"
INSTALLED_APPS = ["django.contrib.contenttypes", "routing", "briefing"]
MIDDLEWARE = ["cors.CorsMiddleware", "django.middleware.common.CommonMiddleware"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
