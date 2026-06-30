"""
apps.forecasting.api.serializers
"""
from rest_framework import serializers
from apps.forecasting.models import DemandPrediction


class DemandPredictionSerializer(serializers.ModelSerializer):
    product_sku_code = serializers.CharField(source="product.sku_code", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = DemandPrediction
        fields = [
            "id",
            "product",
            "product_sku_code",
            "product_name",
            "projected_stockout_date",
            "suggested_order_qty",
            "confidence_score",
            "model_used",
            "status",
            "draft_po",
            "generated_at",
        ]
        read_only_fields = ["id", "generated_at", "product_sku_code", "product_name"]
