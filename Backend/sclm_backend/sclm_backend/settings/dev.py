"""
SCLM Cloud — Development Settings
Extends base.py with dev-friendly overrides.
"""
from .base import *  # noqa: F401, F403

DEBUG = True

ALLOWED_HOSTS = ["*"]

# Disable throttling in development for ease of testing
REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] = []  # noqa: F405

# Use console email backend in development
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
