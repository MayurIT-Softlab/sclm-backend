"""
apps.transportation.api.serializers
"""
from rest_framework import serializers
from apps.transportation.models import Vehicle, DispatchRoute, RouteStop


class VehicleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vehicle
        fields = [
            "id",
            "license_plate",
            "vehicle_type",
            "max_payload_kg",
            "max_volume_m3",
            "is_hazmat_certified",
            "is_available",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class RouteStopSerializer(serializers.ModelSerializer):
    class Meta:
        model = RouteStop
        fields = [
            "id",
            "route",
            "sales_order_id",
            "stop_sequence",
            "delivery_coordinates",
            "delivery_address",
        ]
        read_only_fields = ["id"]


class DispatchRouteSerializer(serializers.ModelSerializer):
    vehicle_plate = serializers.CharField(source="vehicle.license_plate", read_only=True)
    stops = RouteStopSerializer(many=True, read_only=True)
    stop_count = serializers.IntegerField(source="stops.count", read_only=True)

    class Meta:
        model = DispatchRoute
        fields = [
            "id",
            "vehicle",
            "vehicle_plate",
            "driver_id",
            "status",
            "planned_date",
            "total_payload_kg",
            "total_distance_km",
            "stop_count",
            "stops",
            "created_at",
            "completed_at",
        ]
        read_only_fields = ["id", "created_at", "completed_at", "vehicle_plate", "stop_count"]
