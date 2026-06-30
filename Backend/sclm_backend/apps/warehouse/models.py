"""
apps.warehouse.models
Schema: tenant
─────────────────────────────────────────────────────────────────────────────
BinLocation       — 3D spatial coordinate grid node.
                    Coordinate string format: 'ZONE-AISLE-RACK-LEVEL-BIN'
                    e.g., 'DRY-01-12-3-B'
InventoryPosition — Current stock snapshot per bin (used by pick-path optimizer).
─────────────────────────────────────────────────────────────────────────────
"""
import uuid
import re
from django.db import models
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError
from apps.inventory.models import ProductSKU


class ZoneType(models.TextChoices):
    DRY = "DRY", "Dry Storage"
    COLD = "COLD", "Cold Storage"
    HAZMAT = "HAZMAT", "Hazardous Materials"
    RETURNS = "RETURNS", "Returns / Quarantine"


def validate_coordinate_string(value: str):
    """
    Enforces the '3D-01-12-3-B' coordinate string format.
    Pattern: ZONE-AISLE-RACK-LEVEL-BIN (alphanumeric segments separated by hyphens).
    """
    pattern = r'^[A-Z]+(-\d{1,3}){3}-[A-Z0-9]+$'
    if not re.match(pattern, value):
        raise ValidationError(
            f"'{value}' is not a valid coordinate string. "
            "Expected format: ZONE-AISLE-RACK-LEVEL-BIN (e.g., DRY-01-12-3-B)."
        )


class BinLocation(models.Model):
    """
    A single physical bin in the 3D warehouse grid.

    The coordinate_string is the primary spatial identifier used by the
    optimize_pick_path() selector to generate ordered walking paths.
    Sorting by coordinate_string (lexicographic) approximates shortest
    physical walking distance through the warehouse.

    HazmatGeofenceService checks zone_type before allowing put-away.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    coordinate_string = models.CharField(
        max_length=30,
        unique=True,
        db_index=True,
        validators=[validate_coordinate_string],
        help_text=(
            "Unique 3D location string. Format: ZONE-AISLE-RACK-LEVEL-BIN. "
            "Example: DRY-01-12-3-B"
        ),
    )
    zone_type = models.CharField(
        max_length=10,
        choices=ZoneType.choices,
        db_index=True,
    )
    max_weight_kg = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text="Maximum allowable weight for this bin in kilograms.",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Inactive bins are excluded from pick-path generation.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "warehouse"
        verbose_name = "Bin Location"
        verbose_name_plural = "Bin Locations"
        ordering = ["coordinate_string"]
        indexes = [
            models.Index(
                fields=["zone_type", "coordinate_string"],
                name="bin_zone_coord_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.coordinate_string} [{self.zone_type}]"


class InventoryPosition(models.Model):
    """
    A snapshot of how much of each product is in each bin.

    This is updated by the WMS (Warehouse Management System) operations:
    - Put-away (after QC pass): increase current_qty
    - Pick (outbound order): decrease current_qty

    Used by the optimize_pick_path() selector to generate picking lists.
    Unlike StockLedger (which is append-only for financial accuracy),
    InventoryPosition IS mutable — it's a current-state view for operations.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bin = models.ForeignKey(
        BinLocation,
        on_delete=models.PROTECT,
        related_name="inventory_positions",
        db_index=True,
    )
    product = models.ForeignKey(
        ProductSKU,
        on_delete=models.PROTECT,
        related_name="bin_positions",
        db_index=True,
    )
    current_qty = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Current units of this product physically located in this bin.",
    )
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "warehouse"
        verbose_name = "Inventory Position"
        verbose_name_plural = "Inventory Positions"
        unique_together = [("bin", "product")]
        indexes = [
            models.Index(
                fields=["product", "current_qty"],
                name="inv_pos_product_qty_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.current_qty} × {self.product.sku_code} @ {self.bin.coordinate_string}"
