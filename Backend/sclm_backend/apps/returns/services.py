"""
apps.returns.services
─────────────────────────────────────────────────────────────────────────────
RMATriageService — Routes a returned item based on dock worker's disposition:
  RESTOCK → inventory.StockLedgerService.increment_stock()
  SCRAP   → finance.JournalEntryService.write_off_asset()
  REPAIR  → Item held in RETURNS zone bin (no financial action yet)
─────────────────────────────────────────────────────────────────────────────
ARCHITECTURAL RULE:
  This service imports and calls:
    inventory.services.StockLedgerService.increment_stock()
    finance.services.JournalEntryService.write_off_asset()
  It does NOT import models from those modules directly.
─────────────────────────────────────────────────────────────────────────────
"""
import uuid
import logging
from decimal import Decimal
from typing import Optional

from django.db import transaction
from django.utils import timezone

from apps.returns.models import RMAClaim, DispositionTriage

logger = logging.getLogger(__name__)


class RMATriageService:
    """
    The dock triage decision engine for returned goods.

    After the dock worker inspects the physical return, they submit a
    RESTOCK / REPAIR / SCRAP decision. This service atomically routes
    the returned item to the appropriate downstream module.
    """

    @classmethod
    @transaction.atomic
    def triage(
        cls,
        rma_id: uuid.UUID,
        disposition: str,
        triage_notes: str = "",
        actor_id: Optional[uuid.UUID] = None,
    ) -> RMAClaim:
        """
        Executes the triage decision and calls downstream services.

        Args:
            rma_id:       UUID of the RMAClaim to triage.
            disposition:  One of DispositionTriage: RESTOCK, REPAIR, SCRAP.
            triage_notes: Dock worker's inspection notes.
            actor_id:     UUID of the Warehouse Manager performing triage.

        Returns:
            The updated RMAClaim instance.

        Raises:
            ValueError: If RMA is already triaged or disposition is invalid.
        """
        rma = RMAClaim.objects.select_for_update().get(id=rma_id)

        if rma.disposition_triage != DispositionTriage.PENDING:
            raise ValueError(
                f"RMA '{rma_id}' has already been triaged "
                f"(current disposition: '{rma.disposition_triage}'). "
                "Cannot triage twice."
            )

        if disposition not in DispositionTriage.values:
            raise ValueError(
                f"Invalid disposition: '{disposition}'. "
                f"Allowed values: {list(DispositionTriage.values)}."
            )

        if disposition == DispositionTriage.RESTOCK:
            cls._handle_restock(rma, actor_id)
        elif disposition == DispositionTriage.SCRAP:
            cls._handle_scrap(rma, actor_id)
        elif disposition == DispositionTriage.REPAIR:
            cls._handle_repair(rma, actor_id)

        # Update RMA record.
        rma.disposition_triage = disposition
        rma.triage_notes = triage_notes
        rma.triaged_by_actor_id = actor_id
        rma.triaged_at = timezone.now()
        rma.save(update_fields=[
            "disposition_triage",
            "triage_notes",
            "triaged_by_actor_id",
            "triaged_at",
            "restock_ledger_entry_id",
        ])

        logger.info(
            "RMA '%s' triaged as '%s' by actor '%s'.",
            rma_id,
            disposition,
            actor_id,
        )
        return rma

    @classmethod
    def _handle_restock(cls, rma: RMAClaim, actor_id: Optional[uuid.UUID]) -> None:
        """
        RESTOCK: Appends a positive delta to the StockLedger.
        The returned goods re-enter inventory as usable stock.
        """
        from apps.inventory.services import StockLedgerService

        ledger_entry = StockLedgerService.increment_stock(
            product_id=rma.product_id,
            qty=rma.return_quantity,
            reference_module="returns",
            reference_id=rma.id,
            notes=f"Restock from RMA #{str(rma.id)[:8]}: {rma.return_reason}",
            actor_id=actor_id,
        )
        rma.restock_ledger_entry_id = ledger_entry.id
        logger.info(
            "Restocked %d × %s from RMA '%s'.",
            rma.return_quantity,
            rma.product.sku_code,
            rma.id,
        )

    @classmethod
    def _handle_scrap(cls, rma: RMAClaim, actor_id: Optional[uuid.UUID]) -> None:
        """
        SCRAP: Creates an asset write-off JournalEntry.
        The scrapped goods' value is expensed off the balance sheet.
        """
        from apps.finance.services import JournalEntryService

        # Calculate write-off value: unit MAC × return_quantity.
        product = rma.product
        write_off_amount = product.moving_average_cost * Decimal(rma.return_quantity)

        if write_off_amount > Decimal("0"):
            JournalEntryService.write_off_asset(
                rma_id=rma.id,
                write_off_amount=write_off_amount,
                actor_id=actor_id,
            )
            logger.info(
                "Asset write-off: %.2f for RMA '%s' (%d × %s @ %.4f MAC).",
                write_off_amount,
                rma.id,
                rma.return_quantity,
                product.sku_code,
                product.moving_average_cost,
            )
        else:
            logger.warning(
                "RMA '%s' scrap has zero write-off value (MAC=%.4f). No JE created.",
                rma.id,
                product.moving_average_cost,
            )

    @classmethod
    def _handle_repair(cls, rma: RMAClaim, actor_id: Optional[uuid.UUID]) -> None:
        """
        REPAIR: Holds the item in the RETURNS zone.
        No financial action yet — a future repair completion triggers a JournalEntry.
        The item is physically placed in a RETURNS-zoned BinLocation by the warehouse team.
        """
        logger.info(
            "RMA '%s' flagged for REPAIR. Item held in RETURNS zone pending repair.",
            rma.id,
        )
        # TODO: Notify the repair bay (in V2 with WebSockets/push notifications).


class RMAInitiationService:
    """
    Creates a new RMA claim when a retail customer requests a return.
    Called by POST /returns/rma-claims/
    """

    @classmethod
    @transaction.atomic
    def initiate(
        cls,
        sales_order_id: uuid.UUID,
        product_id: uuid.UUID,
        return_quantity: int,
        return_reason: str,
        actor_id: Optional[uuid.UUID] = None,
    ) -> RMAClaim:
        """
        Creates an RMA claim in PENDING status and generates a reverse tracking label.
        """
        from apps.logistics.models import SalesOrder, SalesOrderStatus

        # Validate that the original order was delivered.
        try:
            order = SalesOrder.objects.get(id=sales_order_id, status=SalesOrderStatus.DELIVERED)
        except SalesOrder.DoesNotExist:
            raise ValueError(
                f"SalesOrder '{sales_order_id}' either doesn't exist or "
                "has not been delivered yet. Cannot initiate a return."
            )

        rma = RMAClaim.objects.create(
            sales_order=order,
            product_id=product_id,
            return_quantity=return_quantity,
            return_reason=return_reason,
            disposition_triage=DispositionTriage.PENDING,
        )

        # TODO (Step 6): Generate reverse shipping label via carrier API.
        # label_url = CarrierLabelService.generate_return_label(rma)
        # rma.tracking_label_url = label_url
        # rma.save(update_fields=["tracking_label_url"])

        logger.info(
            "RMA '%s' initiated for SO '%s' — %d × product '%s'.",
            rma.id,
            sales_order_id,
            return_quantity,
            product_id,
        )
        return rma
