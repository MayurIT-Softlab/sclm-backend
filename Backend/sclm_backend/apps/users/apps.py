"""
apps.users — AppConfig
"""
from django.apps import AppConfig


class UsersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.users"
    label = "users"

    def ready(self):
        # Connect signals when Django starts.
        import apps.users.signals  # noqa: F401
