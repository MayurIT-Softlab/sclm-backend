"""
apps.audit_ledger.models
Schema: tenant (per-company isolated schema)
─────────────────────────────────────────────────────────────────────────────
AuditCommit — Immutable Git-style snapshot of every data mutation.

ARCHITECTURAL RULES:
  1. Rows can only ever be INSERT-ed. UPDATE and DELETE are physically
     impossible — enforced by a PostgreSQL BEFORE trigger (see migration
     0002_immutability_trigger.py).
  2. This model has NO API POST endpoint. It is written exclusively by
     Django signals connected to all other operational models.
  3. The actor_id references public.GlobalUser. It is stored as a UUID
     field (not FK) to avoid cross-schema FK constraints.
─────────────────────────────────────────────────────────────────────────────
"""
import uuid
from django.db import models


class AuditAction(models.TextChoices):
    CREATE = "CREATE", "Create"
    UPDATE = "UPDATE", "Update"
    DELETE = "DELETE", "Delete"


class AuditCommit(models.Model):
    """
    An immutable snapshot of a data mutation event.

    Written via post_save / post_delete signals from all operational models.
    The before_state and after_state fields capture the full model state
    as JSONB so the Enterprise Admin can diff any two states.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    table_name = models.CharField(
        max_length=100,
        db_index=True,
        help_text="The Django model table name, e.g., 'inventory_productsku'.",
    )
    record_id = models.UUIDField(
        db_index=True,
        help_text="The UUID primary key of the mutated record.",
    )
    action = models.CharField(
        max_length=10,
        choices=AuditAction.choices,
        db_index=True,
    )
    before_state = models.JSONField(
        null=True,
        blank=True,
        help_text="Full model state BEFORE the mutation (null for CREATE actions).",
    )
    after_state = models.JSONField(
        null=True,
        blank=True,
        help_text="Full model state AFTER the mutation (null for DELETE actions).",
    )
    # Cross-schema reference — stored as UUID, validated at service layer.
    actor_id = models.UUIDField(
        db_index=True,
        help_text="UUID of the GlobalUser who triggered the mutation.",
    )
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="IP address of the actor's request for forensic analysis.",
    )
    timestamp = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )

    class Meta:
        app_label = "audit_ledger"
        ordering = ["-timestamp"]
        verbose_name = "Audit Commit"
        verbose_name_plural = "Audit Commits"
        indexes = [
            models.Index(fields=["table_name", "timestamp"], name="audit_table_ts_idx"),
            models.Index(fields=["actor_id", "timestamp"], name="audit_actor_ts_idx"),
            models.Index(fields=["record_id"], name="audit_record_id_idx"),
        ]

    def __str__(self) -> str:
        return (
            f"[{self.action}] {self.table_name}:{self.record_id} "
            f"by actor:{self.actor_id} @ {self.timestamp}"
        )

    def save(self, *args, **kwargs):
        """
        Enforce append-only at the Django layer as a second safety net.
        The primary enforcement is the PostgreSQL trigger.
        """
        if self.pk and AuditCommit.objects.filter(pk=self.pk).exists():
            raise PermissionError(
                "AuditCommit records are immutable and cannot be updated."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Block deletion at the Django layer. The DB trigger is the primary guard."""
        raise PermissionError(
            "AuditCommit records are immutable and cannot be deleted."
        )
