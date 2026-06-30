"""
apps.logistics.services
─────────────────────────────────────────────────────────────────────────────
ePODCaptureService — The most complex cross-module atomic workflow.
                     Spans 3 modules in ONE database transaction.

OceanFreightPoller — Fetches milestones from carrier APIs.
─────────────────────────────────────────────────────────────────────────────
ATOMIC INTEGRITY PROTOCOL (from Architecture doc):
  The Trigger:  Driver clicks "Sign & Complete" on the mobile app.

  Within a SINGLE transaction.atomic() block:
    Step 1 [logistics]  — Upload signature to S3. Mark SalesOrder=DELIVERED.
    Step 2 [inventory]  — Decrement finished goods stock for each delivered item.
    Step 3 [finance]    — Create revenue recognition JournalEntry.

  If ANY step fails:
    → The database lock collapses.
    → S3 URL is NOT saved (or must be cleaned up).
    → SalesOrder stays at OUT_FOR_DELIVERY.
    → Inventory remains unchanged.
    → No JournalEntry is written.
    → HTTP 500 is returned to the driver's tablet.

CROSS-MODULE CALLS (correct DDD pattern):
  This service imports and calls:
    inventory.services.StockLedgerService.decrement_stock()
    finance.services.JournalEntryService.recognize_revenue()
  It does NOT import models from those modules.
─────────────────────────────────────────────────────────────────────────────
"""
import uuid
import base64
import logging
from decimal import Decimal
from typing import Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


class ePODCaptureService:
    """
    Captures Electronic Proof of Delivery.

    This is the most critical transactional boundary in the system.
    Physical goods, financial books, and driver evidence are reconciled
    in a single atomic operation.
    """

    @classmethod
    @transaction.atomic
    def capture(
        cls,
        sales_order_id: uuid.UUID,
        gps_coordinates: dict,
        signature_base64: str,
        received_by_name: str,
        delivered_items: list[dict],  # [{"product_id": str, "qty": int}]
        actor_id: Optional[uuid.UUID] = None,
    ) -> dict:
        """
        The atomic ePOD capture workflow.

        Args:
            sales_order_id:   UUID of the SalesOrder being delivered.
            gps_coordinates:  {"lat": float, "lng": float}
            signature_base64: Base64-encoded PNG/JPEG of customer signature.
            received_by_name: Name of the person who signed for delivery.
            delivered_items:  List of {"product_id": "<uuid>", "qty": int} dicts.
            actor_id:         UUID of the driver (GlobalUser).

        Returns:
            dict with sales_order_id, status, financial_reconciliation_status, timestamp.

        Raises:
            ValueError: If order is not in OUT_FOR_DELIVERY state.
            ValueError: If insufficient stock for any delivered item.
            ValueError: If finance journal entry is unbalanced.
        """
        from apps.logistics.models import SalesOrder, SalesOrderStatus

        # ── GUARD: Validate order is dispatchable ──────────────────────────
        try:
            # select_for_update() prevents two drivers from simultaneously
            # delivering the same order (concurrent tablet submissions).
            order = SalesOrder.objects.select_for_update().get(id=sales_order_id)
        except SalesOrder.DoesNotExist:
            raise ValueError(f"SalesOrder '{sales_order_id}' not found.")

        if order.status != SalesOrderStatus.OUT_FOR_DELIVERY:
            raise ValueError(
                f"SalesOrder '{sales_order_id}' cannot be delivered. "
                f"Current status: '{order.status}'. "
                "Expected: 'OUT_FOR_DELIVERY'."
            )

        # ── STEP 1: Upload signature to S3 ─────────────────────────────────
        # NOTE: S3 upload happens INSIDE the transaction. If subsequent steps
        # fail, the S3 object will remain (S3 is not transactional). In that
        # case, a cleanup task should remove orphaned S3 objects.
        # A production-grade system uses a compensating transaction or
        # async cleanup Celery task for S3 rollback.
        s3_url = cls._upload_signature_to_s3(
            signature_base64=signature_base64,
            order_id=str(sales_order_id),
        )

        # ── STEP 1b: Update SalesOrder → DELIVERED ─────────────────────────
        order.status = SalesOrderStatus.DELIVERED
        order.pod_signature_s3_url = s3_url
        order.pod_received_by_name = received_by_name
        order.pod_captured_at = timezone.now()
        order.delivery_gps_coordinate = gps_coordinates
        order.save(update_fields=[
            "status",
            "pod_signature_s3_url",
            "pod_received_by_name",
            "pod_captured_at",
            "delivery_gps_coordinate",
        ])
        logger.info("SalesOrder '%s' marked DELIVERED.", sales_order_id)

        # ── STEP 2: Decrement stock for each delivered item ────────────────
        # Import service (not model) — correct DDD cross-module pattern.
        from apps.inventory.services import StockLedgerService

        total_inventory_cost = Decimal("0")
        for item in delivered_items:
            product_id = uuid.UUID(str(item["product_id"]))
            qty = int(item["qty"])

            StockLedgerService.decrement_stock(
                product_id=product_id,
                qty=qty,
                reference_module="logistics",
                reference_id=sales_order_id,
                notes=f"ePOD delivery: SO#{str(sales_order_id)[:8]}",
                actor_id=actor_id,
            )

            # Calculate COGS for journal entry (MAC × qty).
            from apps.inventory.models import ProductSKU
            try:
                product = ProductSKU.objects.get(id=product_id)
                total_inventory_cost += product.moving_average_cost * Decimal(qty)
            except ProductSKU.DoesNotExist:
                pass

        logger.info(
            "Stock decremented for %d item(s) on SO '%s'.",
            len(delivered_items),
            sales_order_id,
        )

        # ── STEP 3: Create double-entry revenue JournalEntry ───────────────
        # Import service (not model) — correct DDD cross-module pattern.
        from apps.finance.services import JournalEntryService

        journal_entry = JournalEntryService.recognize_revenue(
            sales_order_id=sales_order_id,
            revenue_amount=order.order_total,
            inventory_cost=total_inventory_cost,
            actor_id=actor_id,
        )
        logger.info(
            "JournalEntry '%s' created for SO '%s'. "
            "Revenue=%.2f, COGS=%.2f.",
            journal_entry.id,
            sales_order_id,
            order.order_total,
            total_inventory_cost,
        )

        # ── ALL STEPS SUCCEEDED — Transaction will commit ──────────────────
        return {
            "sales_order_id": str(sales_order_id),
            "status": SalesOrderStatus.DELIVERED,
            "financial_reconciliation_status": "COMMITTED",
            "journal_entry_id": str(journal_entry.id),
            "timestamp": timezone.now().isoformat(),
        }

    @staticmethod
    def _upload_signature_to_s3(signature_base64: str, order_id: str) -> str:
        """
        Decodes Base64 signature image and uploads it to AWS S3.
        Returns the S3 object URL.

        On failure, raises an exception which triggers the atomic rollback.
        """
        try:
            image_data = base64.b64decode(signature_base64)
        except Exception as exc:
            raise ValueError(
                f"Invalid signature_base64 — could not decode: {exc}"
            )

        bucket = getattr(settings, "AWS_STORAGE_BUCKET_NAME", "sclm-cloud-epod")
        region = getattr(settings, "AWS_S3_REGION_NAME", "us-east-1")
        key = f"epod/signatures/{order_id}.png"

        try:
            s3 = boto3.client(
                "s3",
                region_name=region,
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            )
            s3.put_object(
                Bucket=bucket,
                Key=key,
                Body=image_data,
                ContentType="image/png",
                ServerSideEncryption="AES256",
            )
            s3_url = f"https://{bucket}.s3.{region}.amazonaws.com/{key}"
            logger.info("Signature uploaded to S3: %s", s3_url)
            return s3_url

        except (BotoCoreError, ClientError) as exc:
            logger.error("S3 upload failed for order '%s': %s", order_id, exc)
            raise ValueError(
                f"ePOD signature upload failed. AWS S3 error: {exc}. "
                "Transaction aborted."
            )


class OceanFreightPoller:
    """
    Polls ocean carrier APIs to update InboundContainer milestones.
    Called by the `poll_ocean_carriers` Celery task every 4 hours.
    Full carrier API integration implemented in Step 6.
    """

    SUPPORTED_CARRIERS = ["maersk", "msc", "cosco", "project44"]

    @classmethod
    def poll_all_active_containers(cls) -> dict:
        """
        Queries all containers that are not yet DELIVERED and polls
        the respective carrier API for milestone updates.
        """
        from apps.logistics.models import InboundContainer, TrackingMilestone

        active_containers = InboundContainer.objects.exclude(
            tracking_milestone=TrackingMilestone.DELIVERED
        ).select_related("po")

        results = {"polled": 0, "updated": 0, "errors": 0}

        for container in active_containers:
            try:
                milestone = cls._fetch_milestone_from_carrier(container)
                if milestone and milestone != container.tracking_milestone:
                    container.tracking_milestone = milestone
                    container.last_polled_at = timezone.now()
                    container.save(update_fields=["tracking_milestone", "last_polled_at"])
                    results["updated"] += 1
                    logger.info(
                        "Container '%s' milestone updated: %s",
                        container.container_number,
                        milestone,
                    )
                else:
                    container.last_polled_at = timezone.now()
                    container.save(update_fields=["last_polled_at"])
                results["polled"] += 1
            except Exception as exc:
                logger.error(
                    "Failed to poll container '%s': %s",
                    container.container_number,
                    exc,
                )
                results["errors"] += 1

        return results

    @classmethod
    def _fetch_milestone_from_carrier(cls, container) -> Optional[str]:
        """
        Placeholder for carrier API call.
        Step 6 implements the actual HTTP client (Project44, Maersk API, etc.)
        """
        # TODO (Step 6): Implement carrier-specific HTTP client
        # if container.ocean_carrier.lower() == "maersk":
        #     return MaerskAPIClient.get_milestone(container.container_number)
        logger.debug(
            "Carrier API poll placeholder for '%s' (%s).",
            container.container_number,
            container.ocean_carrier,
        )
        return None
