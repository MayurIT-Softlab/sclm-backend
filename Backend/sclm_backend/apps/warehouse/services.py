"""
apps.warehouse.services
─────────────────────────────────────────────────────────────────────────────
HazmatGeofenceService — Validates HAZMAT put-away rules before any bin assignment.
PutawayService        — Places received stock into a BinLocation, updates InventoryPosition.
─────────────────────────────────────────────────────────────────────────────
"""
import uuid
import logging
from typing import Optional

from django.db import transaction

from apps.warehouse.models import BinLocation, InventoryPosition, ZoneType

logger = logging.getLogger(__name__)


class HazmatGeofenceService:
    """
    SAFETY-CRITICAL service. Checks the HAZMAT geofence before any put-away.

    Rule: If a ProductSKU.is_hazmat == True, the bin MUST have zone_type == HAZMAT.
    If this check fails, the put-away is blocked and an exception is raised.
    This prevents accidental storage of dangerous goods in non-certified zones.
    """

    @classmethod
    def validate_putaway(cls, product_id: uuid.UUID, bin_id: uuid.UUID) -> None:
        """
        Raises ValueError if HAZMAT product is being placed in a non-HAZMAT bin.
        Called by PutawayService.putaway() before any DB write.
        """
        from apps.inventory.models import ProductSKU

        product = ProductSKU.objects.get(id=product_id)
        bin_loc = BinLocation.objects.get(id=bin_id)

        if product.is_hazmat and bin_loc.zone_type != ZoneType.HAZMAT:
            raise ValueError(
                f"HAZMAT GEOFENCE VIOLATION: "
                f"Product '{product.sku_code}' is classified as hazardous material. "
                f"It cannot be stored in bin '{bin_loc.coordinate_string}' "
                f"(zone: {bin_loc.zone_type}). "
                "Only HAZMAT-zoned bins are permitted. Put-away blocked."
            )

        if not bin_loc.is_active:
            raise ValueError(
                f"Bin '{bin_loc.coordinate_string}' is inactive and cannot receive stock."
            )

        logger.debug(
            "Hazmat geofence OK: '%s' → bin '%s' [%s].",
            product.sku_code,
            bin_loc.coordinate_string,
            bin_loc.zone_type,
        )


class PutawayService:
    """
    Places incoming stock into a specific BinLocation and updates the
    InventoryPosition snapshot for the pick-path optimizer.
    """

    @classmethod
    @transaction.atomic
    def putaway(
        cls,
        product_id: uuid.UUID,
        bin_id: uuid.UUID,
        qty: int,
        actor_id: Optional[uuid.UUID] = None,
    ) -> InventoryPosition:
        """
        1. Validates HAZMAT geofence.
        2. Updates (or creates) the InventoryPosition for the bin × product.
        3. Returns the updated InventoryPosition.
        """
        if qty <= 0:
            raise ValueError(f"Put-away quantity must be positive. Received: {qty}")

        # HAZMAT geofence check — MUST pass before any DB write.
        HazmatGeofenceService.validate_putaway(product_id, bin_id)

        bin_loc = BinLocation.objects.get(id=bin_id)

        position, created = InventoryPosition.objects.select_for_update().get_or_create(
            bin=bin_loc,
            product_id=product_id,
            defaults={"current_qty": 0},
        )
        position.current_qty += qty
        position.save(update_fields=["current_qty", "last_updated"])

        action = "created" if created else "updated"
        logger.info(
            "InventoryPosition %s: %d units of product '%s' in bin '%s'.",
            action,
            position.current_qty,
            product_id,
            bin_loc.coordinate_string,
        )
        return position

    @classmethod
    @transaction.atomic
    def pick(
        cls,
        product_id: uuid.UUID,
        bin_id: uuid.UUID,
        qty: int,
        actor_id: Optional[uuid.UUID] = None,
    ) -> InventoryPosition:
        """
        Reduces InventoryPosition when pickers take items for an outbound order.
        """
        if qty <= 0:
            raise ValueError(f"Pick quantity must be positive. Received: {qty}")

        position = InventoryPosition.objects.select_for_update().get(
            bin_id=bin_id,
            product_id=product_id,
        )
        if position.current_qty < qty:
            raise ValueError(
                f"Insufficient quantity in bin. "
                f"Available: {position.current_qty}, Requested: {qty}."
            )

        position.current_qty -= qty
        position.save(update_fields=["current_qty", "last_updated"])
        logger.info(
            "Picked %d units of product '%s' from bin '%s'. Remaining: %d.",
            qty,
            product_id,
            position.bin.coordinate_string,
            position.current_qty,
        )
        return position
