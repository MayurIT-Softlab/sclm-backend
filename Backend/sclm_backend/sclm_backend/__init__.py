"""
SCLM Cloud — Django Project Package
Ensures the Celery app is loaded when Django starts,
so shared_task decorators in all modules use this app instance.
"""
from .celery import app as celery_app  # noqa: F401

__all__ = ("celery_app",)
