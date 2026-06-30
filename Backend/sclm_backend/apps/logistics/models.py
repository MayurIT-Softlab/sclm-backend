"""
apps.logistics.models
Schema: tenant
─────────────────────────────────────────────────────────────────────────────
InboundContainer — Tracks ocean freight containers via external carrier APIs.
SalesOrder       — Outbound B2B orders, ePOD signature capture.
SalesOrderItem   — Line items for each SalesOrder.
─────────────────────────────────────────────────────────────────────────────
"""
import uuid
from django.db import models
from django.core.validators import MinValueValidator
from apps.inventory.models import ProductSKU
from apps.procurement.models import PurchaseOrder


class TrackingMilestone(models.TextChoices):
    BOOKING_CONFIRMED = "BOOKING_CONFIRMED", "Booking Confirmed"
    DEPARTED_ORIGIN = "DEPARTED_ORIGIN", "Departed Origin Port"
    IN_TRANSIT = "IN_TRANSIT", "In Transit (Open Ocean)"
    ARRIVED_DESTINATION = "ARRIVED_DESTINATION", "Arrived at Destination Port"
    CLEARED_CUSTOMS = "CLEARED_CUSTOMS", "Cleared Customs"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY", "Out for Inland Delivery"
    DELIVERED = "DELIVERED", "Delivered to Warehouse"


class SalesOrderStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    PACKING = "PACKING", "Packing"
    PACKED = "PACKED", "Packed and Ready"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY", "Out for Delivery"
    DELIVERED = "DELIVERED", "Delivered"
    CANCELLED = "CANCELLED", "Cancelled"


class InboundContainer(models.Model):
    """
    Tracks an ocean freight container from origin port to warehouse.

    The `poll_ocean_carriers` Celery task polls the carrier's API every
    4 hours and updates tracking_milestone. This keeps the Logistics
    Manager dashboard current without needing push notifications.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    po = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.PROTECT,
        related_name="containers",
        db_index=True,
        help_text="The PurchaseOrder whose goods are in this container.",
    )
    container_number = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="ISO 6346 container ID, e.g., MSKU1234567.",
    )
    ocean_carrier = models.CharField(
        max_length=100,
        help_text="Carrier name, e.g., 'Maersk', 'MSC', 'COSCO'.",
    )
    carrier_api_ref = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="External tracking reference returned by the carrier API.",
    )
    tracking_milestone = models.CharField(
        max_length=30,
        choices=TrackingMilestone.choices,
        default=TrackingMilestone.BOOKING_CONFIRMED,
        db_index=True,
    )
    origin_port = models.CharField(max_length=100, blank=True, default="")
    destination_port = models.CharField(max_length=100, blank=True, default="")
    estimated_arrival = models.DateField(null=True, blank=True)
    last_polled_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp of the last successful carrier API poll.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "logistics"
        verbose_name = "Inbound Container"
        verbose_name_plural = "Inbound Containers"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.container_number} [{self.ocean_carrier}] → {self.tracking_milestone}"


class SalesOrder(models.Model):
    """
    An outbound B2B order from a retail customer.

    The ePOD (Electronic Proof of Delivery) flow:
      1. Driver submits: GPS coordinates, signature (base64), received_by_name.
      2. ePODCaptureService uploads signature to AWS S3.
      3. Within transaction.atomic():
         - SalesOrder.status → DELIVERED
         - SalesOrder.pod_signature_s3_url → S3 URL
         - inventory.services.StockLedgerService.decrement() for each item
         - finance.services.JournalEntryService.create() for revenue recognition
      If any step fails → entire transaction rolls back → stays OUT_FOR_DELIVERY.

    GPS coordinate stored as JSON; PostGIS geometry added via raw SQL migration.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Cross-schema: customer is a GlobalUser in the public schema.
    customer_id = models.UUIDField(
        db_index=True,
        help_text="UUID of the GlobalUser (Retail Customer) who placed this order.",
    )
    status = models.CharField(
        max_length=20,
        choices=SalesOrderStatus.choices,
        default=SalesOrderStatus.PENDING,
        db_index=True,
    )
    # Delivery address + GPS
    delivery_address = models.CharField(max_length=500, blank=True, default="")
    delivery_gps_coordinate = models.JSONField(
        default=dict,
        help_text=(
            '{"lat": 34.0522, "lng": -118.2437} — '
            "Used by PostGIS routing for DispatchRoute optimization. "
            "Production migration adds native GEOMETRY(Point, 4326) column."
        ),
    )
    # ePOD fields — populated by ePODCaptureService
    pod_signature_s3_url = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text="S3 URL of the customer's delivery signature image.",
    )
    pod_received_by_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Name of the person who received the delivery.",
    )
    pod_captured_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when ePOD was captured.",
    )
    # Dispatch link
    dispatch_route = models.ForeignKey(
        "transportation.DispatchRoute",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sales_orders",
    )
    order_total = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "logistics"
        verbose_name = "Sales Order"
        verbose_name_plural = "Sales Orders"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["status", "created_at"],
                name="so_status_ts_idx",
            ),
            models.Index(fields=["customer_id"], name="so_customer_idx"),
        ]

    def __str__(self) -> str:
        return f"SO#{str(self.id)[:8]} — customer:{str(self.customer_id)[:8]} [{self.status}]"


class SalesOrderItem(models.Model):
    """Line items on a SalesOrder — used by ePODCaptureService to decrement stock."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sales_order = models.ForeignKey(
        SalesOrder,
        on_delete=models.CASCADE,
        related_name="items",
        db_index=True,
    )
    product = models.ForeignKey(
        ProductSKU,
        on_delete=models.PROTECT,
        related_name="sales_order_items",
    )
    quantity = models.IntegerField(validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        validators=[MinValueValidator(0)],
    )

    class Meta:
        app_label = "logistics"
        verbose_name = "Sales Order Item"
        verbose_name_plural = "Sales Order Items"

    def __str__(self) -> str:
        return f"{self.quantity} × {self.product.sku_code}"

    @property
    def line_total(self):
        return self.quantity * self.unit_price
