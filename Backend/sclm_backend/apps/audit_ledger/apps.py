"""
apps.audit_ledger — AppConfig
"""
from django.apps import AppConfig


class AuditLedgerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.audit_ledger"
    label = "audit_ledger"

    def ready(self):
        import apps.audit_ledger.signals  # noqa: F401
