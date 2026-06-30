"""
apps.forecasting.models
Schema: tenant
─────────────────────────────────────────────────────────────────────────────
DemandPrediction — AI-generated reorder signal.
                   Status tracks whether a Draft PO was generated or ignored.
─────────────────────────────────────────────────────────────────────────────
"""
import uuid
from django.db import models


class PredictionStatus(models.TextChoices):
    PENDING = "PENDING", "Pending Review"
    PO_DRAFTED = "PO_DRAFTED", "Draft PO Generated"
    SKIPPED = "SKIPPED", "Ignored by Sourcing Manager"


class DemandPrediction(models.Model):
    """
    An AI-generated demand prediction for a SKU.

    Generated nightly by the Celery task `apps.forecasting.tasks.generate_draft_pos`.
    When status transitions to PO_DRAFTED, a PurchaseOrder is automatically created
    and linked via `draft_po`.

    Sourcing Manager reviews predictions and either:
      - Lets the system auto-approve the draft PO, or
      - Calls /predictions/{id}/mark_ignored/ to set status=SKIPPED.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(
        "inventory.ProductSKU",
        on_delete=models.CASCADE,
        related_name="demand_predictions",
        db_index=True,
    )
    projected_stockout_date = models.DateField(
        db_index=True,
        help_text="Predicted date when stock will reach zero.",
    )
    suggested_order_qty = models.IntegerField(
        default=0,
        help_text="Recommended reorder quantity to cover lead time + safety stock.",
    )
    confidence_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Model confidence 0.00–100.00.",
    )
    model_used = models.CharField(
        max_length=50,
        default="",
        blank=True,
        help_text="Algorithm identifier, e.g., 'ARIMA', 'Prophet', 'ExponentialSmoothing'.",
    )
    status = models.CharField(
        max_length=20,
        choices=PredictionStatus.choices,
        default=PredictionStatus.PENDING,
        db_index=True,
    )
    draft_po = models.ForeignKey(
        "procurement.PurchaseOrder",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="demand_predictions",
        help_text="The auto-generated Draft PO linked to this prediction.",
    )
    generated_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        app_label = "forecasting"
        verbose_name = "Demand Prediction"
        verbose_name_plural = "Demand Predictions"
        ordering = ["-generated_at"]
        indexes = [
            models.Index(
                fields=["projected_stockout_date"],
                name="forecast_stockout_date_idx",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"Prediction for {self.product.sku_code} — "
            f"stockout: {self.projected_stockout_date} [{self.status}]"
        )
