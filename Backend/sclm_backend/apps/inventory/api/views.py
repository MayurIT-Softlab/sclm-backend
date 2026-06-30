"""
apps.inventory.api.views
"""
from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from apps.inventory.models import ProductSKU, StockLedger
from apps.inventory.api.serializers import (
    ProductSKUSerializer,
    StockLedgerSerializer,
    ManualAdjustmentSerializer,
)
from apps.inventory.services import StockLedgerService
from apps.inventory.selectors import get_stock_summary, get_all_stock_balances
from core.pagination import StandardResultsPagination


class ProductSKUViewSet(viewsets.ModelViewSet):
    """
    CRUD for ProductSKU master data.
    """
    queryset = ProductSKU.objects.all().order_by("sku_code")
    serializer_class = ProductSKUSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsPagination
    filter_backends = [filters.SearchFilter]
    search_fields = ["sku_code", "name"]

    @action(detail=True, methods=["get"])
    def stock_summary(self, request, pk=None):
        """GET /inventory/products/{id}/stock_summary/"""
        summary = get_stock_summary(pk)
        return Response(summary)

    @action(detail=False, methods=["get"])
    def all_balances(self, request):
        """GET /inventory/products/all_balances/"""
        balances = get_all_stock_balances()
        return Response(balances)


class StockLedgerViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only view for the immutable stock ledger.
    """
    queryset = StockLedger.objects.all().order_by("-created_at")
    serializer_class = StockLedgerSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["reference_module", "notes"]
    ordering_fields = ["created_at"]

    def get_queryset(self):
        qs = super().get_queryset()
        product_id = self.request.query_params.get("product_id")
        if product_id:
            qs = qs.filter(product_id=product_id)
        return qs

    @action(detail=False, methods=["post"])
    def adjust(self, request):
        """
        POST /inventory/ledger/adjust/
        Cycle count manual adjustment.
        """
        serializer = ManualAdjustmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        try:
            entry = StockLedgerService.apply_manual_adjustment(
                product_id=data["product_id"],
                new_actual_qty=data["new_actual_qty"],
                reason=data["reason"],
                actor_id=request.user.id if request.user.is_authenticated else None,
            )
            return Response(StockLedgerSerializer(entry).data, status=status.HTTP_201_CREATED)
        except ValueError as e:
            # The custom exception handler will format this into a 400
            raise e
