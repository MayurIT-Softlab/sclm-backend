"""
apps.returns.api.serializers
"""
from rest_framework import serializers
from apps.returns.models import RMAClaim, DispositionTriage


class RMAClaimSerializer(serializers.ModelSerializer):
    product_sku_code = serializers.CharField(source="product.sku_code", read_only=True)
    sales_order_status = serializers.CharField(source="sales_order.status", read_only=True)

    class Meta:
        model = RMAClaim
        fields = [
            "id",
            "sales_order",
            "sales_order_status",
            "product",
            "product_sku_code",
            "return_quantity",
            "disposition_triage",
            "refund_amount",
            "return_reason",
            "triage_notes",
            "triaged_by_actor_id",
            "triaged_at",
            "tracking_label_url",
            "restock_ledger_entry_id",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "disposition_triage",
            "triaged_by_actor_id",
            "triaged_at",
            "restock_ledger_entry_id",
            "created_at",
            "updated_at",
            "sales_order_status",
            "product_sku_code",
        ]


class TriageSerializer(serializers.Serializer):
    """Body for POST /returns/rma-claims/{id}/triage/"""
    disposition = serializers.ChoiceField(
        choices=[
            DispositionTriage.RESTOCK,
            DispositionTriage.REPAIR,
            DispositionTriage.SCRAP,
        ],
        help_text="RESTOCK | REPAIR | SCRAP",
    )
    triage_notes = serializers.CharField(max_length=2000, allow_blank=True, default="")
    refund_amount = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        required=False,
        default=0,
        min_value=0,
    )
