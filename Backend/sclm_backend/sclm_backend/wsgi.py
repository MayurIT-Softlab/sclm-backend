"""
SCLM Cloud — WSGI Application Entry Point
"""
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sclm_backend.settings.dev")
application = get_wsgi_application()
