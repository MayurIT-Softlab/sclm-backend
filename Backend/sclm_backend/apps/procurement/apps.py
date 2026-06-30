"""
apps.procurement — AppConfig
"""
from django.apps import AppConfig


class ProcurementConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.procurement"
    label = "procurement"

    def ready(self):
        import apps.procurement.signals  # noqa: F401
