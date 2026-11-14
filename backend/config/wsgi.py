import os
import sys
from pathlib import Path

from django.conf import settings
from django.core.wsgi import get_wsgi_application
from whitenoise import WhiteNoise

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
application = WhiteNoise(get_wsgi_application(), root=str(settings.FRONTEND_DIST), index_file=True)
