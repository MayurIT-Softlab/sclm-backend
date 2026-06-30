"""
apps.inventory.services
─────────────────────────────────────────────────────────────────────────────
StockLedgerService  — Append-only delta writer. Uses select_for_update() to
                      prevent race conditions during concurrent scans.
ValuationEngine     — Recalculates Moving Average Cost on PO receipts.
─────────────────────────────────────────────────────────────────────────────
ARCHITECTURAL RULE:
  This module is called BY OTHER modules (logistics, procurement, returns).
  It must NEVER import models from those modules.
  All cross-module calls flow IN via service arguments (product_id, qty, etc.)
─────────────────────────────────────────────────────────────────────────────
"""
import uuid
import logging
from decimal import Decimal
from typing import Optional

from django.db import transaction
from django.db.models import Sum

logger = logging.getLogger(__name__)


class StockLedgerService:
    """
    The sole gateway for all stock mutations.

    All callers (procurement, logistics, returns) MUST use these methods.
    Direct StockLedger.objects.create() is forbidden outside this service.

    RACE CONDITION PREVENTION:
      select_for_update() acquires a row-level DB lock on the ProductSKU row
      before computing the running balance. This prevents two concurrent
      dock scans from double-counting stock.
    """

    @classmethod
    def get_current_quantity(cls, product_id: uuid.UUID) -> int:
        """
        Returns the current stock level by summing ALL ledger deltas.
        This is the canonical source of truth — never a static counter.
        """
        from apps.inventory.models import StockLedger

        result = StockLedger.objects.filter(
            product_id=product_id
        ).aggregate(total=Sum("delta_quantity"))
        return result["total"] or 0

    @classmethod
    def increment_stock(
        cls,
        product_id: uuid.UUID,
        qty: int,
        reference_module: str,
        reference_id: uuid.UUID,
        unit_cost: Optional[Decimal] = None,
        notes: str = "",
        actor_id: Optional[uuid.UUID] = None,
    ) -> "StockLedger":  # type: ignore
        """
        Appends a positive delta to the StockLedger.
        Called by: procurement.InlineQCGate (on QC pass), returns.RMATriageService (RESTOCK).
        """
        return cls._append_delta(
            product_id=product_id,
            delta=abs(qty),
            reference_module=reference_module,
            reference_id=reference_id,
            unit_cost=unit_cost,
            notes=notes,
            actor_id=actor_id,
        )

    @classmethod
    def decrement_stock(
        cls,
        product_id: uuid.UUID,
        qty: int,
        reference_module: str,
        reference_id: uuid.UUID,
        notes: str = "",
        actor_id: Optional[uuid.UUID] = None,
    ) -> "StockLedger":  # type: ignore
        """
        Appends a NEGATIVE delta to the StockLedger.
        Called by: logistics.ePODCaptureService (on DELIVERED confirmation).

        IMPORTANT: This method is typically called inside transaction.atomic()
        by the ePOD capture flow. If the finance step fails, this decrement
        rolls back automatically.
        """
        # Validate we're not going below zero before writing.
        current_qty = cls.get_current_quantity(product_id)
        if current_qty < qty:
            raise ValueError(
                f"Insufficient stock for product '{product_id}'. "
                f"Requested: -{qty}, Available: {current_qty}. "
                "Transaction aborted."
            )

        return cls._append_delta(
            product_id=product_id,
            delta=-abs(qty),
            reference_module=reference_module,
            reference_id=reference_id,
            notes=notes,
            actor_id=actor_id,
        )

    @classmethod
    @transaction.atomic
    def _append_delta(
        cls,
        product_id: uuid.UUID,
        delta: int,
        reference_module: str,
        reference_id: uuid.UUID,
        unit_cost: Optional[Decimal] = None,
        notes: str = "",
        actor_id: Optional[uuid.UUID] = None,
    ) -> "StockLedger":  # type: ignore
        """
        Internal writer. Acquires select_for_update() lock on the ProductSKU
        row before appending the ledger entry.
        """
        from apps.inventory.models import StockLedger, ProductSKU

        # Lock the product row to prevent concurrent race conditions.
        # This is the SAME pattern as a bank account balance update.
        product = ProductSKU.objects.select_for_update().get(id=product_id)

        entry = StockLedger(
            product=product,
            delta_quantity=delta,
            unit_cost_at_time=unit_cost,
            reference_module=reference_module,
            reference_id=reference_id,
            notes=notes,
            created_by_actor_id=actor_id,
        )
        # Bypass the append-only .save() guard by calling super() directly.
        # This is the ONLY authorised writer.
        super(type(entry), entry).save(force_insert=True)

        logger.info(
            "StockLedger: %+d units for product '%s' [%s:%s].",
            delta,
            product.sku_code,
            reference_module,
            reference_id,
        )
        return entry

    @classmethod
    def apply_manual_adjustment(
        cls,
        product_id: uuid.UUID,
        new_actual_qty: int,
        reason: str,
        actor_id: uuid.UUID,
    ) -> "StockLedger":  # type: ignore
        """
        Cycle count override. Calculates the delta from current balance to
        the newly counted quantity and appends a corrective ledger entry.
        Required by POST /inventory/adjustments/ [ADMIN only].
        """
        if not reason or not reason.strip():
            raise ValueError(
                "Manual adjustments require a mandatory 'reason' field "
                "for the audit ledger."
            )

        current_qty = cls.get_current_quantity(product_id)
        delta = new_actual_qty - current_qty

        if delta == 0:
            raise ValueError(
                "No adjustment needed — counted quantity matches current balance."
            )

        return cls._append_delta(
            product_id=product_id,
            delta=delta,
            reference_module="adjustment",
            reference_id=uuid.uuid4(),  # Unique reference for each adjustment
            notes=reason,
            actor_id=actor_id,
        )


class ValuationEngine:
    """
    Recalculates Moving Average Cost (MAC) when new stock arrives.

    MAC Formula:
      new_mac = (current_qty × old_mac + received_qty × new_unit_cost)
                 ÷ (current_qty + received_qty)

    Called by procurement.InlineQCGate after a successful QC pass.
    """

    @classmethod
    @transaction.atomic
    def recalculate_mac(
        cls,
        product_id: uuid.UUID,
        received_qty: int,
        new_unit_cost: Decimal,
    ) -> Decimal:
        """
        Updates ProductSKU.moving_average_cost using weighted average formula.
        Returns the new MAC value.
        """
        from apps.inventory.models import ProductSKU

        product = ProductSKU.objects.select_for_update().get(id=product_id)

        current_qty = StockLedgerService.get_current_quantity(product_id)
        old_mac = product.moving_average_cost

        if (current_qty + received_qty) == 0:
            new_mac = new_unit_cost
        else:
            new_mac = (
                (Decimal(current_qty) * old_mac)
                + (Decimal(received_qty) * new_unit_cost)
            ) / Decimal(current_qty + received_qty)

        new_mac = new_mac.quantize(Decimal("0.0001"))
        product.moving_average_cost = new_mac
        product.save(update_fields=["moving_average_cost"])

        logger.info(
            "MAC updated for '%s': %.4f → %.4f (received %d @ %.4f).",
            product.sku_code,
            old_mac,
            new_mac,
            received_qty,
            new_unit_cost,
        )
        return new_mac
