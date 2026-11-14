import os
from pathlib import Path

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "local-dashboard-key")
ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1],testserver").split(",")
ROOT_URLCONF = "config.urls"
INSTALLED_APPS = ["markets"]
MIDDLEWARE = []
DATABASES = {}
FRONTEND_DIST = Path(os.getenv("FRONTEND_DIST", Path(__file__).resolve().parents[2] / "frontend/dist/frontend/browser"))
WSGI_APPLICATION = "config.wsgi.application"
