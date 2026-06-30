"""
apps.audit_ledger.services
SnapshotGeneratorService — Captures before/after JSONB state of any model.
Called exclusively by Django signals connected to operational models.
"""
import logging
import json
import uuid
from typing import Optional, Any
from django.db import models as django_models
from django.forms.models import model_to_dict
from django.core.serializers.json import DjangoJSONEncoder

logger = logging.getLogger(__name__)


def _serialize_instance(instance) -> dict:
    """Serialize a Django model instance to a JSON-compatible dict."""
    try:
        data = model_to_dict(instance)
        # Convert UUIDs, Decimals, datetimes to JSON-safe strings.
        return json.loads(json.dumps(data, cls=DjangoJSONEncoder))
    except Exception as exc:
        logger.warning("Could not serialize %s: %s", type(instance).__name__, exc)
        return {"error": "serialization_failed", "model": type(instance).__name__}


class SnapshotGeneratorService:
    """
    The sole writer to the AuditCommit table.

    Called from post_save and post_delete signals on all operational models.
    Captures the before and after state as JSONB.

    NEVER call this from a view or serializer — only from signals.
    """

    @classmethod
    def capture_create(cls, instance, request=None) -> None:
        """Record a CREATE event (no before_state)."""
        cls._write_commit(
            table_name=instance._meta.db_table,
            record_id=instance.pk,
            action="CREATE",
            before_state=None,
            after_state=_serialize_instance(instance),
            request=request,
        )

    @classmethod
    def capture_update(cls, instance, before_state: dict, request=None) -> None:
        """Record an UPDATE event with the state snapshot taken before the save."""
        cls._write_commit(
            table_name=instance._meta.db_table,
            record_id=instance.pk,
            action="UPDATE",
            before_state=before_state,
            after_state=_serialize_instance(instance),
            request=request,
        )

    @classmethod
    def capture_delete(cls, instance, request=None) -> None:
        """Record a DELETE event (no after_state)."""
        cls._write_commit(
            table_name=instance._meta.db_table,
            record_id=instance.pk,
            action="DELETE",
            before_state=_serialize_instance(instance),
            after_state=None,
            request=request,
        )

    @classmethod
    def _write_commit(
        cls,
        table_name: str,
        record_id: Any,
        action: str,
        before_state: Optional[dict],
        after_state: Optional[dict],
        request=None,
    ) -> None:
        from apps.audit_ledger.models import AuditCommit

        actor_id = None
        ip_address = None
        if request and hasattr(request, "user") and request.user.is_authenticated:
            actor_id = request.user.id
            ip_address = cls._get_client_ip(request)

        # Ensure record_id is a UUID
        if not isinstance(record_id, uuid.UUID):
            try:
                record_id = uuid.UUID(str(record_id))
            except (ValueError, AttributeError):
                record_id = uuid.uuid4()  # fallback

        try:
            AuditCommit.objects.create(
                table_name=table_name,
                record_id=record_id,
                action=action,
                before_state=before_state,
                after_state=after_state,
                actor_id=actor_id or uuid.UUID(int=0),
                ip_address=ip_address,
            )
        except Exception as exc:
            # Audit failures must NEVER break the primary operation.
            logger.error(
                "AuditCommit write failed for %s:%s — %s",
                table_name,
                record_id,
                exc,
                exc_info=True,
            )

    @staticmethod
    def _get_client_ip(request) -> Optional[str]:
        """Extract the real client IP, accounting for reverse proxies."""
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")
