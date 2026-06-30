"""
apps.transportation.selectors
─────────────────────────────────────────────────────────────────────────────
PostGIS-based spatial queries for route optimization.

GPS coordinates stored as JSON ({"lat": float, "lng": float}) in the model.
For distance calculations, we use PostgreSQL's ST_Distance via raw SQL.
Production requires: CREATE EXTENSION IF NOT EXISTS postgis; on Neon DB.
─────────────────────────────────────────────────────────────────────────────
"""
import logging
from typing import Optional

from django.db import connection

logger = logging.getLogger(__name__)


def order_stops_by_distance(stops: list[dict], origin: Optional[dict] = None) -> list[dict]:
    """
    Orders a list of delivery stops by geographic distance from the origin
    (warehouse location) using a nearest-neighbor heuristic.

    Each stop dict: {"sales_order_id": uuid, "coordinates": {"lat": f, "lng": f}, "address": str}

    If PostGIS is available: uses ST_Distance for accurate great-circle distance.
    If not available (dev environment): falls back to Euclidean approximation.

    Args:
        stops:  List of stop dicts with coordinates.
        origin: Warehouse GPS coordinates {"lat": ..., "lng": ...}. Defaults to (0, 0).

    Returns:
        Ordered list of stops (nearest-neighbor from origin).
    """
    if not stops:
        return []

    if len(stops) == 1:
        return stops

    # Check if PostGIS is available on this DB connection.
    postgis_available = _check_postgis_available()

    if postgis_available:
        return _order_by_postgis(stops, origin)
    else:
        logger.warning(
            "PostGIS not available — using Euclidean distance approximation for route ordering."
        )
        return _order_by_euclidean(stops, origin)


def _check_postgis_available() -> bool:
    """Returns True if the PostGIS extension is installed on the current schema."""
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM pg_extension WHERE extname = 'postgis';"
            )
            count = cursor.fetchone()[0]
            return count > 0
    except Exception:
        return False


def _order_by_postgis(stops: list[dict], origin: Optional[dict]) -> list[dict]:
    """
    Uses PostgreSQL ST_Distance for accurate geographic distance ordering.

    Nearest-neighbor heuristic:
      Start at origin → find nearest unvisited stop → repeat.
    """
    origin_lat = origin.get("lat", 0) if origin else 0
    origin_lng = origin.get("lng", 0) if origin else 0

    ordered = []
    remaining = list(stops)
    current_lat, current_lng = origin_lat, origin_lng

    while remaining:
        # Build a VALUES clause for the batch distance query.
        # NOTE: Values are extracted into local vars first to avoid the Python
        # restriction on backslash escape sequences inside f-string {} expressions.
        def _make_row(stop):
            so_id = stop["sales_order_id"]
            lng = stop["coordinates"].get("lng", 0)
            lat = stop["coordinates"].get("lat", 0)
            return f"('{so_id}', ST_MakePoint({lng}, {lat})::geography)"

        values_clause = ", ".join(_make_row(s) for s in remaining)

        sql = f"""
            SELECT so_id, ST_Distance(
                point::geography,
                ST_MakePoint(%s, %s)::geography
            ) AS distance_m
            FROM (VALUES {values_clause}) AS t(so_id, point)
            ORDER BY distance_m ASC
            LIMIT 1;
        """

        with connection.cursor() as cursor:
            cursor.execute(sql, [current_lng, current_lat])
            row = cursor.fetchone()

        if not row:
            break

        nearest_id = str(row[0])
        # Find and pop the nearest stop.
        for i, stop in enumerate(remaining):
            if str(stop["sales_order_id"]) == nearest_id:
                nearest = remaining.pop(i)
                ordered.append(nearest)
                current_lat = nearest["coordinates"].get("lat", 0)
                current_lng = nearest["coordinates"].get("lng", 0)
                break

    return ordered


def _order_by_euclidean(stops: list[dict], origin: Optional[dict]) -> list[dict]:
    """
    Fallback Euclidean distance ordering for dev environments without PostGIS.
    NOT accurate for long distances but sufficient for dev/test.
    """
    import math

    origin_lat = origin.get("lat", 0) if origin else 0
    origin_lng = origin.get("lng", 0) if origin else 0

    def distance(stop):
        lat = stop["coordinates"].get("lat", 0)
        lng = stop["coordinates"].get("lng", 0)
        return math.sqrt((lat - origin_lat) ** 2 + (lng - origin_lng) ** 2)

    return sorted(stops, key=distance)


def get_vehicles_with_capacity() -> list[dict]:
    """
    Returns all available vehicles with capacity info.
    Used by GET /transportation/vehicles/
    """
    from apps.transportation.models import Vehicle

    return list(
        Vehicle.objects.filter(is_available=True).order_by("max_payload_kg").values(
            "id",
            "license_plate",
            "vehicle_type",
            "max_payload_kg",
            "max_volume_m3",
            "is_hazmat_certified",
            "is_available",
        )
    )
