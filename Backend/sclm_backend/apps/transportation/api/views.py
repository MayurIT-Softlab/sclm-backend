"""
apps.transportation.api.views
GET/POST   /api/v1/transportation/vehicles/                      [LOGISTICS_MGR, ADMIN]
GET/POST   /api/v1/transportation/routes/                        [LOGISTICS_MGR, ADMIN]
POST       /api/v1/transportation/routes/{id}/complete/          [LOGISTICS_MGR, ADMIN]
GET/POST   /api/v1/transportation/route-stops/                   [LOGISTICS_MGR, ADMIN]
"""
from django.utils import timezone
from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.transportation.models import Vehicle, DispatchRoute, RouteStop, RouteStatus
from apps.transportation.api.serializers import (
    VehicleSerializer,
    DispatchRouteSerializer,
    RouteStopSerializer,
)
from apps.users.permissions import IsLogisticsManager
from core.pagination import StandardResultsPagination


class VehicleViewSet(viewsets.ModelViewSet):
    """Fleet management — CRUD for vehicles."""
    queryset = Vehicle.objects.all().order_by("license_plate")
    serializer_class = VehicleSerializer
    permission_classes = [IsAuthenticated, IsLogisticsManager]
    pagination_class = StandardResultsPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["license_plate", "vehicle_type"]
    ordering_fields = ["license_plate", "max_payload_kg"]

    def get_queryset(self):
        qs = super().get_queryset()
        is_available = self.request.query_params.get("is_available")
        hazmat = self.request.query_params.get("is_hazmat_certified")
        if is_available is not None:
            qs = qs.filter(is_available=is_available.lower() == "true")
        if hazmat is not None:
            qs = qs.filter(is_hazmat_certified=hazmat.lower() == "true")
        return qs


class DispatchRouteViewSet(viewsets.ModelViewSet):
    """
    Dispatch Route management.
    Complete action: transitions route to COMPLETED and marks vehicle as available again.
    """
    queryset = (
        DispatchRoute.objects
        .select_related("vehicle")
        .prefetch_related("stops")
        .order_by("-created_at")
    )
    serializer_class = DispatchRouteSerializer
    permission_classes = [IsAuthenticated, IsLogisticsManager]
    pagination_class = StandardResultsPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["status", "vehicle__license_plate"]
    ordering_fields = ["created_at", "planned_date", "status"]

    def get_queryset(self):
        qs = super().get_queryset()
        route_status = self.request.query_params.get("status")
        planned_date = self.request.query_params.get("planned_date")
        if route_status:
            qs = qs.filter(status=route_status.upper())
        if planned_date:
            qs = qs.filter(planned_date=planned_date)
        return qs

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        """
        POST /api/v1/transportation/routes/{id}/complete/
        Marks the route as COMPLETED and releases the vehicle.
        """
        route = self.get_object()
        if route.status != RouteStatus.EN_ROUTE:
            return Response(
                {"detail": f"Route must be EN_ROUTE to complete. Current status: {route.status}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        route.status = RouteStatus.COMPLETED
        route.completed_at = timezone.now()
        route.save(update_fields=["status", "completed_at"])

        # Release vehicle
        route.vehicle.is_available = True
        route.vehicle.save(update_fields=["is_available"])

        return Response(self.get_serializer(route).data)

    @action(detail=True, methods=["post"])
    def dispatch(self, request, pk=None):
        """
        POST /api/v1/transportation/routes/{id}/dispatch/
        Moves route from PENDING to EN_ROUTE and marks vehicle as unavailable.
        """
        route = self.get_object()
        if route.status != RouteStatus.PENDING:
            return Response(
                {"detail": f"Route must be PENDING to dispatch. Current status: {route.status}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        route.status = RouteStatus.EN_ROUTE
        route.save(update_fields=["status"])
        route.vehicle.is_available = False
        route.vehicle.save(update_fields=["is_available"])
        return Response(self.get_serializer(route).data)


class RouteStopViewSet(viewsets.ModelViewSet):
    """Individual stops on a dispatch route."""
    queryset = RouteStop.objects.select_related("route__vehicle").order_by(
        "route", "stop_sequence"
    )
    serializer_class = RouteStopSerializer
    permission_classes = [IsAuthenticated, IsLogisticsManager]
    pagination_class = StandardResultsPagination

    def get_queryset(self):
        qs = super().get_queryset()
        route_id = self.request.query_params.get("route_id")
        if route_id:
            qs = qs.filter(route_id=route_id)
        return qs
