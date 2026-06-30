"""
apps.transportation — AppConfig
"""
from django.apps import AppConfig


class TransportationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.transportation"
    label = "transportation"

    def ready(self):
        import apps.transportation.signals  # noqa: F401
