"""
apps.logistics.api.views
GET/POST   /api/v1/logistics/containers/                      [LOGISTICS_MGR, ADMIN]
GET/POST   /api/v1/logistics/sales-orders/                    [LOGISTICS_MGR, RETAIL_USER, ADMIN]
POST       /api/v1/logistics/sales-orders/{id}/capture_pod/   [LOGISTICS_MGR, ADMIN]
GET/POST   /api/v1/logistics/sales-order-items/               [LOGISTICS_MGR, ADMIN]
"""
from django.utils import timezone
from django.db import transaction
from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.logistics.models import (
    InboundContainer,
    SalesOrder,
    SalesOrderItem,
    SalesOrderStatus,
)
from apps.logistics.api.serializers import (
    InboundContainerSerializer,
    SalesOrderSerializer,
    SalesOrderItemSerializer,
    ePODCaptureSerializer,
)
from apps.users.permissions import IsLogisticsManager
from core.pagination import StandardResultsPagination


class InboundContainerViewSet(viewsets.ModelViewSet):
    """
    Ocean container tracking.
    tracking_milestone is updated by the Celery `poll_ocean_carriers` task.
    """
    queryset = (
        InboundContainer.objects
        .select_related("po")
        .order_by("-created_at")
    )
    serializer_class = InboundContainerSerializer
    permission_classes = [IsAuthenticated, IsLogisticsManager]
    pagination_class = StandardResultsPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["container_number", "ocean_carrier", "tracking_milestone"]
    ordering_fields = ["estimated_arrival", "created_at"]

    def get_queryset(self):
        qs = super().get_queryset()
        milestone = self.request.query_params.get("milestone")
        po_id = self.request.query_params.get("po_id")
        if milestone:
            qs = qs.filter(tracking_milestone=milestone.upper())
        if po_id:
            qs = qs.filter(po_id=po_id)
        return qs


class SalesOrderViewSet(viewsets.ModelViewSet):
    """
    Outbound B2B orders.

    capture_pod action: Implements the ePOD flow within an atomic transaction.
    If finance JournalEntry creation fails, the SalesOrder status rolls back.
    """
    queryset = (
        SalesOrder.objects
        .prefetch_related("items__product")
        .order_by("-created_at")
    )
    serializer_class = SalesOrderSerializer
    permission_classes = [IsAuthenticated, IsLogisticsManager]
    pagination_class = StandardResultsPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["status"]
    ordering_fields = ["created_at", "order_total", "status"]

    def get_queryset(self):
        qs = super().get_queryset()
        order_status = self.request.query_params.get("status")
        customer_id = self.request.query_params.get("customer_id")
        # RETAIL_USER can only see their own orders
        user_role = getattr(self.request, "user_role", None)
        if user_role == "RETAIL_USER":
            qs = qs.filter(customer_id=self.request.user.id)
        else:
            if customer_id:
                qs = qs.filter(customer_id=customer_id)
        if order_status:
            qs = qs.filter(status=order_status.upper())
        return qs

    @action(detail=True, methods=["post"])
    def capture_pod(self, request, pk=None):
        """
        POST /api/v1/logistics/sales-orders/{id}/capture_pod/
        Captures Electronic Proof of Delivery within an atomic transaction.
        If any step fails (including finance JournalEntry), the whole transaction rolls back.
        """
        sales_order = self.get_object()
        if sales_order.status != SalesOrderStatus.OUT_FOR_DELIVERY:
            return Response(
                {
                    "detail": (
                        f"Order must be OUT_FOR_DELIVERY to capture ePOD. "
                        f"Current status: {sales_order.status}"
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = ePODCaptureSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            with transaction.atomic():
                # 1. Update the SalesOrder
                sales_order.status = SalesOrderStatus.DELIVERED
                sales_order.pod_signature_s3_url = data["pod_signature_s3_url"]
                sales_order.pod_received_by_name = data["received_by_name"]
                sales_order.pod_captured_at = timezone.now()
                sales_order.delivery_gps_coordinate = {
                    "lat": data["delivery_gps_lat"],
                    "lng": data["delivery_gps_lng"],
                }
                sales_order.save(update_fields=[
                    "status", "pod_signature_s3_url", "pod_received_by_name",
                    "pod_captured_at", "delivery_gps_coordinate", "updated_at",
                ])

                # 2. Decrement stock ledger for each item
                from apps.inventory.services import StockLedgerService
                for item in sales_order.items.all():
                    StockLedgerService.decrement(
                        product_id=item.product_id,
                        quantity=item.quantity,
                        reference_module="logistics",
                        reference_id=sales_order.id,
                        actor_id=request.user.id,
                    )

                # 3. Finance — revenue recognition journal entry
                # (If JournalEntryService raises, entire atomic block rolls back)
                from apps.finance.services import JournalEntryService
                JournalEntryService.create_revenue_recognition(
                    sales_order=sales_order,
                    actor_id=request.user.id,
                )

        except Exception as exc:
            return Response(
                {"detail": f"ePOD capture failed and was rolled back: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(SalesOrderSerializer(sales_order).data)


class SalesOrderItemViewSet(viewsets.ModelViewSet):
    """Line items for Sales Orders."""
    queryset = SalesOrderItem.objects.select_related("product", "sales_order").all()
    serializer_class = SalesOrderItemSerializer
    permission_classes = [IsAuthenticated, IsLogisticsManager]
    pagination_class = StandardResultsPagination

    def get_queryset(self):
        qs = super().get_queryset()
        so_id = self.request.query_params.get("sales_order_id")
        if so_id:
            qs = qs.filter(sales_order_id=so_id)
        return qs
