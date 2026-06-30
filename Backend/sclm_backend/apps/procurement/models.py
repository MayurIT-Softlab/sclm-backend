"""
apps.procurement.models
Schema: tenant
─────────────────────────────────────────────────────────────────────────────
PurchaseOrder  — The header record for a supplier purchase.
POLineItem     — Individual product lines on a PO with inline QC tracking.
─────────────────────────────────────────────────────────────────────────────
"""
import uuid
from decimal import Decimal
from django.db import models
from django.core.validators import MinValueValidator


class POStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    APPROVED = "APPROVED", "Approved"
    IN_TRANSIT = "IN_TRANSIT", "In Transit"
    RECEIVED = "RECEIVED", "Received"
    QC_FAILED = "QC_FAILED", "QC Failed"
    CANCELLED = "CANCELLED", "Cancelled"


class PurchaseOrder(models.Model):
    """
    The header record for a supplier purchase order.

    total_cost is the sum of all POLineItem (unit_cost × ordered_qty).
    It is denormalised here for fast dashboard queries and finance integration.
    JournalEntryService reads total_cost when creating BUDGET_ENCUMBRANCE entries.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vendor_name = models.CharField(max_length=255)
    vendor_contact_email = models.EmailField(blank=True, default="")
    status = models.CharField(
        max_length=20,
        choices=POStatus.choices,
        default=POStatus.DRAFT,
        db_index=True,
    )
    # Denormalised total — updated by POService.recalculate_total() on line item changes.
    total_cost = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Total cost of all line items. Kept in sync by POService.",
    )
    approved_by_actor_id = models.UUIDField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    expected_delivery_date = models.DateField(null=True, blank=True)
    encumbrance_journal_entry_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "procurement"
        verbose_name = "Purchase Order"
        verbose_name_plural = "Purchase Orders"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"PO#{str(self.id)[:8]} — {self.vendor_name} [{self.status}]"


class POLineItem(models.Model):
    """
    A single product line on a PurchaseOrder.

    qc_passed_qty is populated by the Inline QC Gate after physical inspection.
    The gap (ordered_qty - qc_passed_qty) represents QC-failed units.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    po = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.CASCADE,
        related_name="line_items",
        db_index=True,
    )
    product = models.ForeignKey(
        "inventory.ProductSKU",
        on_delete=models.PROTECT,
        related_name="po_line_items",
    )
    ordered_qty = models.IntegerField(validators=[MinValueValidator(1)])
    unit_cost = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    # Populated by the QC Gate after physical inspection.
    qc_passed_qty = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Units that passed quality inspection.",
    )
    qc_failed_qty = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Units that failed quality inspection.",
    )
    qc_notes = models.CharField(max_length=255, blank=True, default="")
    qc_completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "procurement"
        verbose_name = "PO Line Item"
        verbose_name_plural = "PO Line Items"

    def __str__(self) -> str:
        return f"{self.ordered_qty} × {self.product.sku_code} on PO#{str(self.po_id)[:8]}"

    @property
    def line_total(self) -> Decimal:
        """Unit cost × ordered qty — used by POService.recalculate_total()."""
        return self.unit_cost * self.ordered_qty