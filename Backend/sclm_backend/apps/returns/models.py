"""
apps.returns.models
Schema: tenant
─────────────────────────────────────────────────────────────────────────────
RMAClaim — Return Merchandise Authorization.
           Dock triage routes it to RESTOCK, REPAIR, or SCRAP.
─────────────────────────────────────────────────────────────────────────────
"""
import uuid
from django.db import models
from django.core.validators import MinValueValidator
from apps.logistics.models import SalesOrder
from apps.inventory.models import ProductSKU


class DispositionTriage(models.TextChoices):
    PENDING = "PENDING", "Pending Triage"
    RESTOCK = "RESTOCK", "Restock (Returned to Inventory)"
    REPAIR = "REPAIR", "Repair (Sent to Repair Bay)"
    SCRAP = "SCRAP", "Scrap (Write Off Asset)"


class RMAClaim(models.Model):
    """
    A Return Merchandise Authorization claim.

    Flow:
      1. Retail Customer calls POST /returns/rma-claims/ → status=PENDING.
      2. Warehouse Manager receives physical goods, inspects them, then calls
         POST /returns/rma-claims/{id}/triage/ with disposition.
      3. RMATriageService routes the outcome:
         - RESTOCK → inventory.services.increment_stock(+delta)
         - SCRAP   → finance.services.write_off_asset(unit_cost × qty)
         - REPAIR  → item held in RETURNS zone bin (no immediate action)
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sales_order = models.ForeignKey(
        SalesOrder,
        on_delete=models.PROTECT,
        related_name="rma_claims",
        db_index=True,
        help_text="The original SalesOrder being returned.",
    )
    product = models.ForeignKey(
        ProductSKU,
        on_delete=models.PROTECT,
        related_name="rma_claims",
        db_index=True,
    )
    return_quantity = models.IntegerField(
        validators=[MinValueValidator(1)],
        help_text="Number of units being returned.",
    )
    disposition_triage = models.CharField(
        max_length=10,
        choices=DispositionTriage.choices,
        default=DispositionTriage.PENDING,
        db_index=True,
    )
    refund_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Amount to refund to the customer for this return.",
    )
    # Customer-provided return reason.
    return_reason = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Customer's stated reason for the return.",
    )
    # Dock worker triage notes.
    triage_notes = models.TextField(
        blank=True,
        default="",
        help_text="Warehouse manager's assessment notes after physical inspection.",
    )
    # Cross-schema: UUID of the GlobalUser who performed triage.
    triaged_by_actor_id = models.UUIDField(
        null=True,
        blank=True,
        help_text="UUID of the Warehouse Manager who performed the dock triage.",
    )
    triaged_at = models.DateTimeField(null=True, blank=True)
    # Link to the reverse tracking label.
    tracking_label_url = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="URL to the generated return shipping label.",
    )
    # Link to the restocked StockLedger entry (set by RMATriageService).
    restock_ledger_entry_id = models.UUIDField(
        null=True,
        blank=True,
        help_text="UUID of the StockLedger entry created on RESTOCK disposition.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "returns"
        verbose_name = "RMA Claim"
        verbose_name_plural = "RMA Claims"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["disposition_triage", "created_at"],
                name="rma_triage_ts_idx",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"RMA#{str(self.id)[:8]} — {self.product.sku_code} × {self.return_quantity} "
            f"[{self.disposition_triage}]"
        )
