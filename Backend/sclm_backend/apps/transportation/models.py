"""
apps.transportation.models
Schema: tenant
─────────────────────────────────────────────────────────────────────────────
Vehicle       — Fleet asset with payload capacity and hazmat certification.
DispatchRoute — A driver's assigned multi-stop delivery run.
RouteStop     — Individual delivery stop on a DispatchRoute (PostGIS coordinates
                stored as JSON; ST_Distance queries run via raw SQL in selectors).
─────────────────────────────────────────────────────────────────────────────
POSTGIS NOTE:
  GPS coordinates are stored as JSONField {"lat": float, "lng": float}.
  The PostGIS extension handles spatial distance calculations in selectors.py
  via raw SQL: ST_Distance(ST_MakePoint(lng, lat)::geography, ...).
  A production migration adds a native GEOMETRY(Point, 4326) column alongside
  the JSON field for full PostGIS index support.
─────────────────────────────────────────────────────────────────────────────
"""
import uuid
from django.db import models
from django.core.validators import MinValueValidator


class RouteStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    EN_ROUTE = "EN_ROUTE", "En Route"
    COMPLETED = "COMPLETED", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"


class Vehicle(models.Model):
    """
    A physical delivery vehicle in the company's fleet.

    FleetCapacityService reads max_payload_kg and is_hazmat_certified
    when assigning vehicles to batches of SalesOrders.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    license_plate = models.CharField(max_length=20, unique=True)
    vehicle_type = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="e.g., 'Box Truck', 'Semi-Trailer', 'Refrigerated Van'.",
    )
    max_payload_kg = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text="Maximum cargo weight this vehicle can legally carry.",
    )
    max_volume_m3 = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Maximum cargo volume in cubic metres.",
    )
    is_hazmat_certified = models.BooleanField(
        default=False,
        db_index=True,
        help_text=(
            "If True, this vehicle can carry HAZMAT products. "
            "FleetCapacityService checks this before assignment."
        ),
    )
    is_available = models.BooleanField(
        default=True,
        db_index=True,
        help_text="False when the vehicle is currently on an active route.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "transportation"
        verbose_name = "Vehicle"
        verbose_name_plural = "Vehicles"
        ordering = ["license_plate"]

    def __str__(self) -> str:
        hazmat = " [HAZMAT Cert]" if self.is_hazmat_certified else ""
        return f"{self.license_plate} — {self.max_payload_kg}kg{hazmat}"


class DispatchRoute(models.Model):
    """
    A planned multi-stop delivery run assigned to one driver + vehicle.

    Created by FleetCapacityService after PostGIS route optimization.
    Multiple RouteStops are linked to this record (one per SalesOrder drop).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.PROTECT,
        related_name="dispatch_routes",
        db_index=True,
    )
    # Cross-schema: driver is a GlobalUser in the public schema.
    driver_id = models.UUIDField(
        db_index=True,
        help_text="UUID of the GlobalUser assigned as driver for this route.",
    )
    status = models.CharField(
        max_length=15,
        choices=RouteStatus.choices,
        default=RouteStatus.PENDING,
        db_index=True,
    )
    planned_date = models.DateField(
        null=True,
        blank=True,
        help_text="The date this route is scheduled to execute.",
    )
    # Aggregated metrics populated by FleetCapacityService.
    total_payload_kg = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Total weight of all cargo on this route.",
    )
    total_distance_km = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Estimated total distance calculated by PostGIS route optimizer.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "transportation"
        verbose_name = "Dispatch Route"
        verbose_name_plural = "Dispatch Routes"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["status", "planned_date"],
                name="route_status_date_idx",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"Route#{str(self.id)[:8]} — {self.vehicle.license_plate} "
            f"[{self.status}] driver:{str(self.driver_id)[:8]}"
        )


class RouteStop(models.Model):
    """
    One delivery stop on a DispatchRoute (corresponds to one SalesOrder).

    GPS coordinates stored as JSON for dev compatibility.
    Production uses PostGIS ST_MakePoint for distance calculations.
    Stop order is determined by the PostGIS route optimizer.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    route = models.ForeignKey(
        DispatchRoute,
        on_delete=models.CASCADE,
        related_name="stops",
        db_index=True,
    )
    # UUID reference to logistics.SalesOrder (cross-app — not FK per DDD rules).
    sales_order_id = models.UUIDField(
        db_index=True,
        help_text="UUID of the SalesOrder being delivered at this stop.",
    )
    stop_sequence = models.PositiveSmallIntegerField(
        help_text="The driver's ordered stop number (1 = first stop).",
    )
    # GPS coordinates as JSON — PostGIS geometry added via raw migration in production.
    delivery_coordinates = models.JSONField(
        default=dict,
        help_text='{"lat": 34.0522, "lng": -118.2437}',
    )
    delivery_address = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        app_label = "transportation"
        verbose_name = "Route Stop"
        verbose_name_plural = "Route Stops"
        ordering = ["route", "stop_sequence"]
        unique_together = [("route", "stop_sequence")]

    def __str__(self) -> str:
        return f"Stop #{self.stop_sequence} on Route#{str(self.route_id)[:8]}"
