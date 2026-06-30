"""
apps.audit_ledger.api.serializers
"""
from rest_framework import serializers
from apps.audit_ledger.models import AuditCommit


class AuditCommitSerializer(serializers.ModelSerializer):
    """Read-only serializer for AuditCommit records."""

    class Meta:
        model = AuditCommit
        fields = (
            "id", "table_name", "record_id", "action",
            "before_state", "after_state", "actor_id",
            "ip_address", "timestamp",
        )
        read_only_fields = fields
