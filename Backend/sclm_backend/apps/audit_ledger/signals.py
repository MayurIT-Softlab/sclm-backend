"""
apps.audit_ledger.signals
─────────────────────────────────────────────────────────────────────────────
Connects Django post_save / post_delete signals from ALL operational models
to the SnapshotGeneratorService.

This module is the ONLY authorised writer to the AuditCommit table.
Signals fire asynchronously after each model save/delete, capturing
the before/after JSONB state without blocking the main request.

BEFORE_STATE CAPTURE PATTERN:
  Django's post_save signal provides the saved instance AFTER the mutation.
  To capture the before_state for UPDATE events, we use a pre_save signal
  to snapshot the old state from the DB before the write happens.
─────────────────────────────────────────────────────────────────────────────
"""
import logging
from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver

from apps.audit_ledger.services import SnapshotGeneratorService, _serialize_instance

logger = logging.getLogger(__name__)

# ─── Models to audit (all operational tenant-schema models) ───────────────
from apps.inventory.models import ProductSKU, StockLedger
from apps.procurement.models import PurchaseOrder, POLineItem
from apps.warehouse.models import BinLocation, InventoryPosition
from apps.logistics.models import SalesOrder, InboundContainer
from apps.returns.models import RMAClaim
from apps.finance.models import ChartOfAccounts, JournalEntry

AUDITED_MODELS = [
    ProductSKU, PurchaseOrder, POLineItem,
    BinLocation, SalesOrder, InboundContainer,
    RMAClaim, ChartOfAccounts, JournalEntry,
]

# Store before-states for UPDATE detection (keyed by model instance pk).
_before_state_cache: dict = {}


def _connect_audit_signals(model_class):
    """Connects pre_save (before capture) and post_save/delete (commit) for a model."""

    @receiver(pre_save, sender=model_class, weak=False)
    def capture_before_state(sender, instance, **kwargs):
        """Snapshot the before-state before any UPDATE write."""
        if instance.pk:
            try:
                existing = sender.objects.get(pk=instance.pk)
                _before_state_cache[(sender.__name__, str(instance.pk))] = (
                    _serialize_instance(existing)
                )
            except sender.DoesNotExist:
                pass  # This is a CREATE — no before state

    @receiver(post_save, sender=model_class, weak=False)
    def audit_on_save(sender, instance, created, **kwargs):
        """Commit the AuditCommit record after a save."""
        cache_key = (sender.__name__, str(instance.pk))
        before_state = _before_state_cache.pop(cache_key, None)

        if created:
            SnapshotGeneratorService.capture_create(instance)
        else:
            SnapshotGeneratorService.capture_update(instance, before_state or {})

    @receiver(post_delete, sender=model_class, weak=False)
    def audit_on_delete(sender, instance, **kwargs):
        """Commit the AuditCommit record after a delete."""
        SnapshotGeneratorService.capture_delete(instance)


# Connect signals for all audited models.
for _model in AUDITED_MODELS:
    _connect_audit_signals(_model)

logger.debug(
    "Audit signals connected for %d models: %s",
    len(AUDITED_MODELS),
    [m.__name__ for m in AUDITED_MODELS],
)
