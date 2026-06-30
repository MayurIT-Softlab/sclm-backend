"""
apps.logistics.api.serializers
"""
from rest_framework import serializers
from apps.logistics.models import InboundContainer, SalesOrder, SalesOrderItem


class InboundContainerSerializer(serializers.ModelSerializer):
    po_vendor = serializers.CharField(source="po.vendor_name", read_only=True)
    po_status = serializers.CharField(source="po.status", read_only=True)

    class Meta:
        model = InboundContainer
        fields = [
            "id",
            "po",
            "po_vendor",
            "po_status",
            "container_number",
            "ocean_carrier",
            "carrier_api_ref",
            "tracking_milestone",
            "origin_port",
            "destination_port",
            "estimated_arrival",
            "last_polled_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "last_polled_at", "created_at", "updated_at",
                            "po_vendor", "po_status"]


class SalesOrderItemSerializer(serializers.ModelSerializer):
    product_sku_code = serializers.CharField(source="product.sku_code", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    line_total = serializers.DecimalField(max_digits=18, decimal_places=4, read_only=True)

    class Meta:
        model = SalesOrderItem
        fields = [
            "id",
            "sales_order",
            "product",
            "product_sku_code",
            "product_name",
            "quantity",
            "unit_price",
            "line_total",
        ]
        read_only_fields = ["id", "line_total", "product_sku_code", "product_name"]


class SalesOrderSerializer(serializers.ModelSerializer):
    items = SalesOrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = SalesOrder
        fields = [
            "id",
            "customer_id",
            "status",
            "delivery_address",
            "delivery_gps_coordinate",
            "pod_signature_s3_url",
            "pod_received_by_name",
            "pod_captured_at",
            "dispatch_route",
            "order_total",
            "notes",
            "items",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "pod_signature_s3_url",
            "pod_received_by_name",
            "pod_captured_at",
            "created_at",
            "updated_at",
        ]


class ePODCaptureSerializer(serializers.Serializer):
    """Body for POST /logistics/sales-orders/{id}/capture_pod/"""
    received_by_name = serializers.CharField(max_length=255)
    delivery_gps_lat = serializers.FloatField()
    delivery_gps_lng = serializers.FloatField()
    # In production this would be a base64 field or S3 presigned URL
    pod_signature_s3_url = serializers.URLField(
        help_text="S3 URL of the uploaded signature image."
    )
