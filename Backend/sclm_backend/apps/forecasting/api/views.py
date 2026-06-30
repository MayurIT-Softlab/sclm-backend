"""
apps.forecasting.api.views
GET/POST  /api/v1/forecasting/predictions/           [SOURCING_MGR, ADMIN]
GET       /api/v1/forecasting/predictions/{id}/      [SOURCING_MGR, ADMIN]
POST      /api/v1/forecasting/predictions/{id}/mark_ignored/  [SOURCING_MGR, ADMIN]
"""
from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.forecasting.models import DemandPrediction
from apps.forecasting.api.serializers import DemandPredictionSerializer
from apps.users.permissions import IsSourcingManager
from core.pagination import StandardResultsPagination


class DemandPredictionViewSet(viewsets.ModelViewSet):
    """
    Full CRUD for DemandPrediction records.

    In production, predictions are auto-generated nightly by the Celery task
    `apps.forecasting.tasks.generate_draft_pos`. This ViewSet also allows
    manual creation and status transitions.
    """
    queryset = DemandPrediction.objects.all().select_related("product").order_by("-generated_at")
    serializer_class = DemandPredictionSerializer
    permission_classes = [IsAuthenticated, IsSourcingManager]
    pagination_class = StandardResultsPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["product__sku_code", "product__name", "status"]
    ordering_fields = ["projected_stockout_date", "generated_at", "confidence_score"]

    def get_queryset(self):
        qs = super().get_queryset()
        status_filter = self.request.query_params.get("status")
        product_id = self.request.query_params.get("product_id")
        if status_filter:
            qs = qs.filter(status=status_filter.upper())
        if product_id:
            qs = qs.filter(product_id=product_id)
        return qs

    @action(detail=True, methods=["post"])
    def mark_ignored(self, request, pk=None):
        """
        POST /api/v1/forecasting/predictions/{id}/mark_ignored/
        Sourcing Manager marks a prediction as ignored (won't generate PO).
        """
        prediction = self.get_object()
        if prediction.status == DemandPrediction.PredictionStatus.SKIPPED:
            return Response(
                {"detail": "This prediction is already ignored."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        prediction.status = DemandPrediction.PredictionStatus.SKIPPED
        prediction.save(update_fields=["status"])
        serializer = self.get_serializer(prediction)
        return Response(serializer.data)
