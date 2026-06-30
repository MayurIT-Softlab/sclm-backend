import uuid
from django.db import models
from django.core.validators import MinValueValidator

class ProductSKU(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sku_code = models.CharField(max_length=50, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    weight_kg = models.DecimalField(max_digits=10, decimal_places=4, default=0, validators=[MinValueValidator(0)])
    volume_m3 = models.DecimalField(max_digits=10, decimal_places=6, default=0, validators=[MinValueValidator(0)])
    is_hazmat = models.BooleanField(default=False, db_index=True)
    moving_average_cost = models.DecimalField(max_digits=14, decimal_places=4, default=0, validators=[MinValueValidator(0)])
    reorder_point = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    supplier_lead_days = models.IntegerField(default=7, validators=[MinValueValidator(0)])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "inventory"
        verbose_name = "Product SKU"
        verbose_name_plural = "Product SKUs"
        ordering = ["sku_code"]

    def __str__(self):
        return self.sku_code

class StockLedger(models.Model):
    class ReferenceModule(models.TextChoices):
        PROCUREMENT = "procurement", "Procurement"
        LOGISTICS = "logistics", "Logistics"
        RETURNS = "returns", "Returns"
        ADJUSTMENT = "adjustment", "Adjustment"
        FORECASTING = "forecasting", "Forecasting"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(ProductSKU, on_delete=models.PROTECT, related_name="stock_ledger_entries", db_index=True)
    delta_quantity = models.IntegerField()
    unit_cost_at_time = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    reference_module = models.CharField(max_length=20, choices=ReferenceModule.choices, db_index=True)
    reference_id = models.UUIDField(db_index=True)
    notes = models.CharField(max_length=500, blank=True, default="")
    created_by_actor_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        app_label = "inventory"
        verbose_name = "Stock Ledger Entry"
        verbose_name_plural = "Stock Ledger Entries"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["product", "created_at"], name="stock_product_ts_idx"),
            models.Index(fields=["reference_module", "reference_id"], name="stock_ref_idx"),
        ]

    def save(self, *args, **kwargs):
        if self.pk and StockLedger.objects.filter(pk=self.pk).exists():
            raise PermissionError("Immutable")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Immutable")