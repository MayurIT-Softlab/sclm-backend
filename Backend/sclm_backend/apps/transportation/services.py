"""
apps.transportation.services
─────────────────────────────────────────────────────────────────────────────
FleetCapacityService — Matches a batch of SalesOrders to available vehicles
                       based on aggregated weight/volume requirements.
─────────────────────────────────────────────────────────────────────────────
"""
import uuid
import logging
from decimal import Decimal
from typing import Optional

from django.db import transaction

logger = logging.getLogger(__name__)


class FleetCapacityService:
    """
    Calculates the aggregated cargo requirements for a batch of SalesOrders
    and matches the optimal vehicle from the available fleet.

    Checks:
      1. Total weight (kg) does not exceed Vehicle.max_payload_kg.
      2. If any item is HAZMAT, only Vehicle.is_hazmat_certified vehicles qualify.
      3. Vehicle.is_available must be True.

    After assignment, updates Vehicle.is_available = False and creates a DispatchRoute.
    """

    @classmethod
    @transaction.atomic
    def assign_and_create_route(
        cls,
        sales_order_ids: list[uuid.UUID],
        driver_id: uuid.UUID,
        planned_date=None,
        actor_id: Optional[uuid.UUID] = None,
    ) -> "DispatchRoute":  # type: ignore
        """
        Main entry point. Takes a list of SalesOrder UUIDs, calculates their
        combined cargo requirements, finds the best vehicle, and creates a
        DispatchRoute with ordered stops.
        """
        from apps.transportation.models import Vehicle, DispatchRoute, RouteStop
        from apps.logistics.models import SalesOrder, SalesOrderItem

        # ── Step 1: Calculate total cargo requirements ─────────────────────
        total_weight_kg = Decimal("0")
        total_volume_m3 = Decimal("0")
        requires_hazmat = False
        stops_data = []

        for so_id in sales_order_ids:
            order = SalesOrder.objects.get(id=so_id)
            items = SalesOrderItem.objects.filter(
                sales_order=order
            ).select_related("product")

            for item in items:
                total_weight_kg += item.product.weight_kg * item.quantity
                total_volume_m3 += item.product.volume_m3 * item.quantity
                if item.product.is_hazmat:
                    requires_hazmat = True

            stops_data.append({
                "sales_order_id": so_id,
                "coordinates": order.delivery_gps_coordinate,
                "address": order.delivery_address,
            })

        logger.info(
            "Route planning: %d orders, %.2f kg, %.2f m³, HAZMAT=%s.",
            len(sales_order_ids),
            total_weight_kg,
            total_volume_m3,
            requires_hazmat,
        )

        # ── Step 2: Find the optimal available vehicle ─────────────────────
        vehicle = cls._select_vehicle(
            total_weight_kg=total_weight_kg,
            requires_hazmat=requires_hazmat,
        )

        # ── Step 3: Create DispatchRoute ───────────────────────────────────
        route = DispatchRoute.objects.create(
            vehicle=vehicle,
            driver_id=driver_id,
            planned_date=planned_date,
            total_payload_kg=total_weight_kg,
        )

        # ── Step 4: Optimise stop order via PostGIS (selectors.py) ─────────
        from apps.transportation.selectors import order_stops_by_distance
        ordered_stops = order_stops_by_distance(stops_data)

        for seq, stop in enumerate(ordered_stops, start=1):
            RouteStop.objects.create(
                route=route,
                sales_order_id=stop["sales_order_id"],
                stop_sequence=seq,
                delivery_coordinates=stop["coordinates"],
                delivery_address=stop.get("address", ""),
            )

        # ── Step 5: Mark vehicle as unavailable ────────────────────────────
        vehicle.is_available = False
        vehicle.save(update_fields=["is_available"])

        logger.info(
            "DispatchRoute '%s' created: vehicle=%s, %d stops.",
            route.id,
            vehicle.license_plate,
            len(ordered_stops),
        )
        return route

    @classmethod
    def _select_vehicle(
        cls,
        total_weight_kg: Decimal,
        requires_hazmat: bool,
    ) -> "Vehicle":  # type: ignore
        """
        Selects the smallest available vehicle that satisfies cargo requirements.
        Prefers vehicles with max_payload_kg closest to (but above) the cargo weight.
        """
        from apps.transportation.models import Vehicle

        qs = Vehicle.objects.filter(
            is_available=True,
            max_payload_kg__gte=total_weight_kg,
        ).order_by("max_payload_kg")  # smallest-first → most efficient fit

        if requires_hazmat:
            qs = qs.filter(is_hazmat_certified=True)

        vehicle = qs.first()
        if not vehicle:
            raise ValueError(
                f"No available vehicle can carry {total_weight_kg} kg"
                f"{' (HAZMAT certified required)' if requires_hazmat else ''}. "
                "Add more fleet capacity or reduce the order batch."
            )
        return vehicle
