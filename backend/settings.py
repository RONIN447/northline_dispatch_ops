SECRET_KEY = "development-only-change-before-deployment"
DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
ROOT_URLCONF = "urls"
INSTALLED_APPS = ["django.contrib.contenttypes", "routing"]
MIDDLEWARE = ["django.middleware.common.CommonMiddleware"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
