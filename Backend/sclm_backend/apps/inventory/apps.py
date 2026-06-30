"""
apps.inventory — AppConfig
"""
from django.apps import AppConfig


class InventoryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.inventory"
    label = "inventory"

    def ready(self):
        import apps.inventory.signals  # noqa: F401
