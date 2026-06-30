"""
apps.subscriptions.api.serializers
"""
from rest_framework import serializers
from apps.subscriptions.models import Client


class ClientPlanSerializer(serializers.ModelSerializer):
    """
    Read-only view of the tenant's current subscription plan.
    Used by GET /api/v1/subscriptions/current-plan/
    """
    class Meta:
        model = Client
        fields = (
            "id",
            "company_name",
            "plan_tier",
            "is_active",
            "subscription_expires_at",
            "created_at",
        )
        read_only_fields = fields
