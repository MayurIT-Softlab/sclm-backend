"""
apps.procurement.api.views
GET/POST   /api/v1/procurement/purchase-orders/              [SOURCING_MGR, ADMIN]
GET        /api/v1/procurement/purchase-orders/{id}/         [SOURCING_MGR, ADMIN]
POST       /api/v1/procurement/purchase-orders/{id}/approve/ [ADMIN]
GET/POST   /api/v1/procurement/line-items/                   [SOURCING_MGR, ADMIN]
POST       /api/v1/procurement/line-items/{id}/qc_gate/      [WAREHOUSE_MGR, ADMIN]
"""
from django.utils import timezone
from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.procurement.models import PurchaseOrder, POLineItem, POStatus
from apps.procurement.api.serializers import (
    PurchaseOrderSerializer,
    POLineItemSerializer,
    QCGateSerializer,
)
from apps.users.permissions import IsSourcingManager, IsAdminRole, IsWarehouseManager
from core.pagination import StandardResultsPagination


class PurchaseOrderViewSet(viewsets.ModelViewSet):
    """
    CRUD for Purchase Orders.

    Approval workflow:
      DRAFT → APPROVED: POST /purchase-orders/{id}/approve/  (ADMIN only)
      APPROVED → IN_TRANSIT: updated by logistics when container is created.
    """
    queryset = (
        PurchaseOrder.objects
        .prefetch_related("line_items__product")
        .order_by("-created_at")
    )
    serializer_class = PurchaseOrderSerializer
    permission_classes = [IsAuthenticated, IsSourcingManager]
    pagination_class = StandardResultsPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["vendor_name", "status"]
    ordering_fields = ["created_at", "total_cost", "status"]

    def get_queryset(self):
        qs = super().get_queryset()
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter.upper())
        return qs

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsAdminRole])
    def approve(self, request, pk=None):
        """
        POST /api/v1/procurement/purchase-orders/{id}/approve/
        Transitions PO from DRAFT to APPROVED. ADMIN only.
        """
        po = self.get_object()
        if po.status != POStatus.DRAFT:
            return Response(
                {"detail": f"Cannot approve a PO in '{po.status}' status. Must be DRAFT."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        po.status = POStatus.APPROVED
        po.approved_by_actor_id = request.user.id
        po.approved_at = timezone.now()
        po.save(update_fields=["status", "approved_by_actor_id", "approved_at", "updated_at"])
        serializer = self.get_serializer(po)
        return Response(serializer.data)


class POLineItemViewSet(viewsets.ModelViewSet):
    """
    CRUD for PO Line Items.
    QC Gate action populates qc_passed_qty / qc_failed_qty after physical inspection.
    """
    queryset = (
        POLineItem.objects
        .select_related("product", "po")
        .order_by("po__created_at")
    )
    serializer_class = POLineItemSerializer
    permission_classes = [IsAuthenticated, IsSourcingManager]
    pagination_class = StandardResultsPagination

    def get_queryset(self):
        qs = super().get_queryset()
        po_id = self.request.query_params.get("po_id")
        if po_id:
            qs = qs.filter(po_id=po_id)
        return qs

    @action(
        detail=True,
        methods=["post"],
        permission_classes=[IsAuthenticated, IsWarehouseManager],
    )
    def qc_gate(self, request, pk=None):
        """
        POST /api/v1/procurement/line-items/{id}/qc_gate/
        Warehouse Manager records QC results after physical inspection.
        Body: { qc_passed_qty, qc_failed_qty, qc_notes }
        """
        line_item = self.get_object()
        serializer = QCGateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        total = data["qc_passed_qty"] + data["qc_failed_qty"]
        if total != line_item.ordered_qty:
            return Response(
                {
                    "detail": (
                        f"qc_passed_qty ({data['qc_passed_qty']}) + "
                        f"qc_failed_qty ({data['qc_failed_qty']}) = {total}, "
                        f"but ordered_qty = {line_item.ordered_qty}. They must match."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        line_item.qc_passed_qty = data["qc_passed_qty"]
        line_item.qc_failed_qty = data["qc_failed_qty"]
        line_item.qc_notes = data.get("qc_notes", "")
        line_item.qc_completed_at = timezone.now()
        line_item.save(
            update_fields=["qc_passed_qty", "qc_failed_qty", "qc_notes", "qc_completed_at"]
        )
        return Response(POLineItemSerializer(line_item).data)
