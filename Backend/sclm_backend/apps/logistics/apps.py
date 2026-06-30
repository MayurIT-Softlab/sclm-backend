"""
apps.logistics — AppConfig
"""
from django.apps import AppConfig


class LogisticsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.logistics"
    label = "logistics"

    def ready(self):
        import apps.logistics.signals  # noqa: F401
