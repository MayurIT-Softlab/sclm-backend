"""
apps.warehouse.selectors
─────────────────────────────────────────────────────────────────────────────
optimize_pick_path() — Generates a geographically-sequenced picking list
                       for warehouse pickers, minimising walking distance.
─────────────────────────────────────────────────────────────────────────────
The coordinate_string format is: ZONE-AISLE-RACK-LEVEL-BIN
  e.g., COLD-01-04-2-A < COLD-01-04-2-B < COLD-01-05-1-A < DRY-01-01-1-A

Lexicographic ORDER BY on coordinate_string approximates the shortest
physical walking path (same zone → same aisle → ascending rack/level).
For full TSP optimization, the transportation.selectors PostGIS functions
are used. This selector handles in-warehouse pick sequencing.
─────────────────────────────────────────────────────────────────────────────
"""
import uuid
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def optimize_pick_path(sales_order_id: uuid.UUID) -> list[dict]:
    """
    Returns an ordered list of pick instructions for a given SalesOrder.

    Each instruction specifies:
      - bin_coordinate: where to walk
      - product_sku: what to pick
      - qty_to_pick: how many units
      - sequence: the picker's walking order (1 = first bin)

    Sorting is done by BinLocation.coordinate_string (lexicographic),
    which maps to physical aisle order (Zone → Aisle → Rack → Level → Bin).

    Args:
        sales_order_id: UUID of the SalesOrder to generate a pick list for.

    Returns:
        List of dicts ordered by pick sequence.
    """
    from apps.logistics.models import SalesOrderItem
    from apps.warehouse.models import InventoryPosition, BinLocation

    # Get all items on this order.
    items = SalesOrderItem.objects.filter(
        sales_order_id=sales_order_id
    ).select_related("product")

    if not items.exists():
        return []

    product_ids = [item.product_id for item in items]
    qty_map = {item.product_id: item.quantity for item in items}

    # Find bin positions for each product, ordered by coordinate string.
    positions = (
        InventoryPosition.objects.filter(
            product_id__in=product_ids,
            current_qty__gt=0,
            bin__is_active=True,
        )
        .select_related("bin", "product")
        .order_by("bin__coordinate_string")
    )

    pick_path = []
    remaining = dict(qty_map)  # copy to track unfulfilled quantities

    for idx, position in enumerate(positions, start=1):
        product_id = position.product_id
        if product_id not in remaining or remaining[product_id] <= 0:
            continue

        qty_needed = remaining[product_id]
        qty_available_in_bin = position.current_qty
        qty_to_pick = min(qty_needed, qty_available_in_bin)

        if qty_to_pick <= 0:
            continue

        pick_path.append({
            "sequence": idx,
            "bin_id": str(position.bin_id),
            "bin_coordinate": position.bin.coordinate_string,
            "zone_type": position.bin.zone_type,
            "product_id": str(product_id),
            "product_sku": position.product.sku_code,
            "product_name": position.product.name,
            "qty_to_pick": qty_to_pick,
        })
        remaining[product_id] -= qty_to_pick

    # Report any items that couldn't be fulfilled from bin positions.
    unfulfilled = {
        str(pid): qty for pid, qty in remaining.items() if qty > 0
    }
    if unfulfilled:
        logger.warning(
            "Pick path for SO '%s' has unfulfilled quantities: %s",
            sales_order_id,
            unfulfilled,
        )

    logger.info(
        "Pick path generated for SO '%s': %d stops, %d unfulfilled SKUs.",
        sales_order_id,
        len(pick_path),
        len(unfulfilled),
    )
    return pick_path


def search_bins(
    zone_type: Optional[str] = None,
    coordinate_prefix: Optional[str] = None,
    is_active: bool = True,
) -> list[dict]:
    """
    Searches BinLocations by zone and/or coordinate prefix.
    Used by GET /warehouse/bins/ endpoint.
    """
    from apps.warehouse.models import BinLocation

    qs = BinLocation.objects.filter(is_active=is_active)
    if zone_type:
        qs = qs.filter(zone_type=zone_type)
    if coordinate_prefix:
        qs = qs.filter(coordinate_string__startswith=coordinate_prefix.upper())

    return list(
        qs.order_by("coordinate_string").values(
            "id", "coordinate_string", "zone_type", "max_weight_kg", "is_active"
        )
    )
