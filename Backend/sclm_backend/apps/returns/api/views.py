"""
apps.returns.api.views
GET/POST   /api/v1/returns/rma-claims/                        [WAREHOUSE_MGR, RETAIL_USER, ADMIN]
GET        /api/v1/returns/rma-claims/{id}/                   [WAREHOUSE_MGR, RETAIL_USER, ADMIN]
POST       /api/v1/returns/rma-claims/{id}/triage/            [WAREHOUSE_MGR, ADMIN]

Triage Flow (from schema doc):
  RESTOCK → inventory.services.increment_stock(+delta)
  SCRAP   → finance.services.write_off_asset(unit_cost × qty)
  REPAIR  → held in RETURNS zone bin (no immediate action)
"""
from django.utils import timezone
from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.returns.models import RMAClaim, DispositionTriage
from apps.returns.api.serializers import RMAClaimSerializer, TriageSerializer
from apps.users.permissions import IsWarehouseManager
from core.pagination import StandardResultsPagination


class RMAClaimViewSet(viewsets.ModelViewSet):
    """
    Return Merchandise Authorization lifecycle management.

    POST by RETAIL_USER creates the claim (PENDING).
    POST /{id}/triage/ by WAREHOUSE_MGR resolves the physical inspection.
    """
    queryset = (
        RMAClaim.objects
        .select_related("product", "sales_order")
        .order_by("-created_at")
    )
    serializer_class = RMAClaimSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["product__sku_code", "disposition_triage"]
    ordering_fields = ["created_at", "disposition_triage"]

    def get_queryset(self):
        qs = super().get_queryset()
        disposition = self.request.query_params.get("disposition")
        user_role = getattr(self.request, "user_role", None)
        # RETAIL_USER can only see their own RMA claims
        if user_role == "RETAIL_USER":
            qs = qs.filter(sales_order__customer_id=self.request.user.id)
        if disposition:
            qs = qs.filter(disposition_triage=disposition.upper())
        return qs

    def perform_create(self, serializer):
        serializer.save()

    @action(
        detail=True,
        methods=["post"],
        permission_classes=[IsAuthenticated, IsWarehouseManager],
    )
    def triage(self, request, pk=None):
        """
        POST /api/v1/returns/rma-claims/{id}/triage/
        Warehouse Manager resolves the physical dock inspection.

        Body: { disposition: RESTOCK|REPAIR|SCRAP, triage_notes, refund_amount }
        """
        rma = self.get_object()
        if rma.disposition_triage != DispositionTriage.PENDING:
            return Response(
                {"detail": f"RMA has already been triaged as '{rma.disposition_triage}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = TriageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        rma.disposition_triage = data["disposition"]
        rma.triage_notes = data.get("triage_notes", "")
        rma.refund_amount = data.get("refund_amount", 0)
        rma.triaged_by_actor_id = request.user.id
        rma.triaged_at = timezone.now()

        # Route outcome based on disposition
        if data["disposition"] == DispositionTriage.RESTOCK:
            from apps.inventory.services import StockLedgerService
            ledger_entry = StockLedgerService.increment(
                product_id=rma.product_id,
                quantity=rma.return_quantity,
                reference_module="returns",
                reference_id=rma.id,
                actor_id=request.user.id,
            )
            rma.restock_ledger_entry_id = ledger_entry.id

        elif data["disposition"] == DispositionTriage.SCRAP:
            # Write off the asset value in the finance ledger
            try:
                from apps.finance.services import JournalEntryService
                JournalEntryService.create_asset_write_off(
                    rma=rma,
                    actor_id=request.user.id,
                )
            except Exception as exc:
                return Response(
                    {"detail": f"Asset write-off failed: {exc}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
        # REPAIR: held in RETURNS zone — no immediate stock or finance action.

        rma.save()
        return Response(RMAClaimSerializer(rma).data)
