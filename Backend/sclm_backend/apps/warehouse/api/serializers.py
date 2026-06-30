"""
apps.warehouse.api.serializers
"""
from rest_framework import serializers
from apps.warehouse.models import BinLocation, InventoryPosition


class BinLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = BinLocation
        fields = [
            "id",
            "coordinate_string",
            "zone_type",
            "max_weight_kg",
            "is_active",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class InventoryPositionSerializer(serializers.ModelSerializer):
    bin_coordinate = serializers.CharField(source="bin.coordinate_string", read_only=True)
    bin_zone = serializers.CharField(source="bin.zone_type", read_only=True)
    product_sku_code = serializers.CharField(source="product.sku_code", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = InventoryPosition
        fields = [
            "id",
            "bin",
            "bin_coordinate",
            "bin_zone",
            "product",
            "product_sku_code",
            "product_name",
            "current_qty",
            "last_updated",
        ]
        read_only_fields = ["id", "last_updated", "bin_coordinate", "bin_zone",
                            "product_sku_code", "product_name"]
