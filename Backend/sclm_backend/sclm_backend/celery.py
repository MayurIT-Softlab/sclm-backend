"""
SCLM Cloud — Celery Application
Configures the Celery instance used by all 11 modules for async tasks.
"""
import os
from celery import Celery

# Set the default Django settings module for the Celery worker process.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sclm_backend.settings.dev")

app = Celery("sclm_backend")

# Load Celery configuration from Django settings (prefixed with CELERY_).
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks.py files in all registered Django apps.
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Sanity-check task. Run with: pipenv run celery -A sclm_backend call sclm_backend.celery.debug_task"""
    print(f"[Celery] Request: {self.request!r}")
