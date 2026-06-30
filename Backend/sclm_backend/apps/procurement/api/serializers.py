"""
apps.procurement.api.serializers
"""
from rest_framework import serializers
from apps.procurement.models import PurchaseOrder, POLineItem


class POLineItemSerializer(serializers.ModelSerializer):
    product_sku_code = serializers.CharField(source="product.sku_code", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    line_total = serializers.DecimalField(
        max_digits=18, decimal_places=2, read_only=True
    )

    class Meta:
        model = POLineItem
        fields = [
            "id",
            "po",
            "product",
            "product_sku_code",
            "product_name",
            "ordered_qty",
            "unit_cost",
            "line_total",
            "qc_passed_qty",
            "qc_failed_qty",
            "qc_notes",
            "qc_completed_at",
        ]
        read_only_fields = ["id", "line_total", "product_sku_code", "product_name"]


class PurchaseOrderSerializer(serializers.ModelSerializer):
    line_items = POLineItemSerializer(many=True, read_only=True)
    line_item_count = serializers.IntegerField(source="line_items.count", read_only=True)

    class Meta:
        model = PurchaseOrder
        fields = [
            "id",
            "vendor_name",
            "vendor_contact_email",
            "status",
            "total_cost",
            "approved_by_actor_id",
            "approved_at",
            "expected_delivery_date",
            "encumbrance_journal_entry_id",
            "line_item_count",
            "line_items",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "approved_by_actor_id",
            "approved_at",
            "encumbrance_journal_entry_id",
            "created_at",
            "updated_at",
        ]


class POApproveSerializer(serializers.Serializer):
    """Used by the /approve/ custom action."""
    pass  # No additional body fields — approval is triggered by the authenticated user


class QCGateSerializer(serializers.Serializer):
    """Body for POST /procurement/line-items/{id}/qc_gate/"""
    qc_passed_qty = serializers.IntegerField(min_value=0)
    qc_failed_qty = serializers.IntegerField(min_value=0)
    qc_notes = serializers.CharField(max_length=255, allow_blank=True, default="")
