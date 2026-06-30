"""
apps.inventory.api.serializers
"""
from rest_framework import serializers
from apps.inventory.models import ProductSKU, StockLedger


class ProductSKUSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductSKU
        fields = (
            "id", "sku_code", "name", "description",
            "volume_m3", "weight_kg", "is_hazmat",
            "reorder_point", "supplier_lead_days",
            "moving_average_cost", "created_at", "updated_at"
        )
        read_only_fields = ("id", "moving_average_cost", "created_at", "updated_at")


class StockLedgerSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockLedger
        fields = (
            "id", "product", "delta_quantity", "unit_cost_at_time",
            "reference_module", "reference_id", "notes",
            "created_by_actor_id", "created_at"
        )
        read_only_fields = fields


class ManualAdjustmentSerializer(serializers.Serializer):
    """Payload for POST /inventory/adjustments/"""
    product_id = serializers.UUIDField()
    new_actual_qty = serializers.IntegerField(min_value=0)
    reason = serializers.CharField(min_length=5, required=True)
