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

# Use local memory cache in development to avoid requiring a local Redis server running
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "sclm-local-dev-cache",
    }
}

# Run Celery tasks synchronously in-process (eager mode) during development.
# This bypasses the need for a Redis broker/worker process locally.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache"
