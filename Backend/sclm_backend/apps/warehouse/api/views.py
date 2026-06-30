"""
apps.warehouse.api.views
GET/POST   /api/v1/warehouse/bins/                           [WAREHOUSE_MGR, ADMIN]
GET/POST   /api/v1/warehouse/positions/                      [WAREHOUSE_MGR, ADMIN]
GET        /api/v1/warehouse/positions/by_product/?sku_code= [WAREHOUSE_MGR, ADMIN]
"""
from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.warehouse.models import BinLocation, InventoryPosition
from apps.warehouse.api.serializers import BinLocationSerializer, InventoryPositionSerializer
from apps.users.permissions import IsWarehouseManager
from core.pagination import StandardResultsPagination


class BinLocationViewSet(viewsets.ModelViewSet):
    """
    CRUD for warehouse 3D bin grid.
    Coordinate format: ZONE-AISLE-RACK-LEVEL-BIN (e.g., DRY-01-12-3-B)
    """
    queryset = BinLocation.objects.all().order_by("coordinate_string")
    serializer_class = BinLocationSerializer
    permission_classes = [IsAuthenticated, IsWarehouseManager]
    pagination_class = StandardResultsPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["coordinate_string", "zone_type"]
    ordering_fields = ["coordinate_string", "zone_type", "max_weight_kg"]

    def get_queryset(self):
        qs = super().get_queryset()
        zone_type = self.request.query_params.get("zone_type")
        is_active = self.request.query_params.get("is_active")
        if zone_type:
            qs = qs.filter(zone_type=zone_type.upper())
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() == "true")
        return qs


class InventoryPositionViewSet(viewsets.ModelViewSet):
    """
    Current stock snapshot per bin.
    Used by the pick-path optimizer and put-away service.
    """
    queryset = (
        InventoryPosition.objects
        .select_related("bin", "product")
        .order_by("bin__coordinate_string")
    )
    serializer_class = InventoryPositionSerializer
    permission_classes = [IsAuthenticated, IsWarehouseManager]
    pagination_class = StandardResultsPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["product__sku_code", "product__name", "bin__coordinate_string"]
    ordering_fields = ["current_qty", "last_updated"]

    def get_queryset(self):
        qs = super().get_queryset()
        product_id = self.request.query_params.get("product_id")
        bin_id = self.request.query_params.get("bin_id")
        zone_type = self.request.query_params.get("zone_type")
        if product_id:
            qs = qs.filter(product_id=product_id)
        if bin_id:
            qs = qs.filter(bin_id=bin_id)
        if zone_type:
            qs = qs.filter(bin__zone_type=zone_type.upper())
        return qs

    @action(detail=False, methods=["get"])
    def by_product(self, request):
        """
        GET /api/v1/warehouse/positions/by_product/?sku_code=SKU-001
        Returns all bin positions for a given SKU.
        """
        sku_code = request.query_params.get("sku_code")
        if not sku_code:
            return Response(
                {"detail": "sku_code query parameter is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        qs = self.get_queryset().filter(product__sku_code=sku_code, current_qty__gt=0)
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)
