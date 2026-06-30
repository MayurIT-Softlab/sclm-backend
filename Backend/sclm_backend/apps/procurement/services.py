"""
apps.procurement.services
─────────────────────────────────────────────────────────────────────────────
POStateMachineService — Manages PurchaseOrder state transitions.
                        APPROVED transition atomically calls finance.encumber_budget().
InlineQCGate          — Dock scanning gate that splits QC pass/fail quantities.
─────────────────────────────────────────────────────────────────────────────
"""
import uuid
import logging
from decimal import Decimal
from typing import Optional

from django.db import transaction
from django.utils import timezone

from apps.procurement.models import PurchaseOrder, POLineItem, POStatus

logger = logging.getLogger(__name__)

# Valid state machine transitions
VALID_TRANSITIONS = {
    POStatus.DRAFT: [POStatus.APPROVED, POStatus.CANCELLED],
    POStatus.APPROVED: [POStatus.IN_TRANSIT, POStatus.CANCELLED],
    POStatus.IN_TRANSIT: [POStatus.RECEIVED],
    POStatus.RECEIVED: [],  # Terminal state — no further transitions
    POStatus.QC_FAILED: [],  # Terminal state
    POStatus.CANCELLED: [],  # Terminal state
}


class POStateMachineService:
    """
    The authoritative state machine for PurchaseOrders.

    Only this service may change a PO's status. Views that attempt
    direct PO.status = ... writes will be rejected (enforced by code review).

    The DRAFT → APPROVED transition is the most critical: it atomically
    calls finance.services.encumber_budget() within the same DB transaction.
    If the finance step fails (e.g., Chart of Accounts is misconfigured),
    the PO status does NOT change.
    """

    @classmethod
    @transaction.atomic
    def transition_to_approved(
        cls,
        po_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> PurchaseOrder:
        """
        Transitions PO from DRAFT → APPROVED.

        ATOMIC SIDE EFFECT:
          Calls finance.services.JournalEntryService.encumber_budget()
          within the same transaction. If finance fails → PO stays DRAFT.
        """
        po = PurchaseOrder.objects.select_for_update().get(id=po_id)
        cls._assert_valid_transition(po, POStatus.APPROVED)

        # ── Cross-module call: finance encumbrance ─────────────────────────
        from apps.finance.services import JournalEntryService

        journal_entry = JournalEntryService.encumber_budget(
            po_id=po.id,
            total_amount=po.total_cost,
            actor_id=actor_id,
        )
        logger.info(
            "Budget encumbered: JE '%s' for PO '%s' (%.2f).",
            journal_entry.id,
            po_id,
            po.total_cost,
        )

        # ── Update PO status ───────────────────────────────────────────────
        po.status = POStatus.APPROVED
        po.approved_by_actor_id = actor_id
        po.approved_at = timezone.now()
        po.encumbrance_journal_entry_id = journal_entry.id
        po.save(update_fields=[
            "status",
            "approved_by_actor_id",
            "approved_at",
            "encumbrance_journal_entry_id",
        ])

        logger.info("PO '%s' transitioned to APPROVED by actor '%s'.", po_id, actor_id)
        return po

    @classmethod
    @transaction.atomic
    def transition(
        cls,
        po_id: uuid.UUID,
        new_status: str,
        actor_id: Optional[uuid.UUID] = None,
    ) -> PurchaseOrder:
        """
        Generic state transition for non-approval transitions
        (e.g., APPROVED → IN_TRANSIT, IN_TRANSIT → RECEIVED).
        """
        po = PurchaseOrder.objects.select_for_update().get(id=po_id)
        cls._assert_valid_transition(po, new_status)
        po.status = new_status
        po.save(update_fields=["status"])
        logger.info(
            "PO '%s' transitioned to '%s' by actor '%s'.", po_id, new_status, actor_id
        )
        return po

    @staticmethod
    def _assert_valid_transition(po: PurchaseOrder, new_status: str) -> None:
        """Raises ValueError if the transition is illegal per the state machine."""
        allowed = VALID_TRANSITIONS.get(po.status, [])
        if new_status not in allowed:
            raise ValueError(
                f"Invalid PO status transition: '{po.status}' → '{new_status}'. "
                f"Allowed transitions from '{po.status}': {allowed}."
            )


class InlineQCGate:
    """
    Processes dock barcode scanning for received PO goods.

    When goods arrive:
      1. Dock worker scans each item. System records pass/fail per line.
      2. For PASSED items: inventory.StockLedgerService.increment_stock()
      3. For FAILED items: quantity held in QC_HOLD, routed to returns.
      4. ValuationEngine.recalculate_mac() runs on passed items.
    """

    @classmethod
    @transaction.atomic
    def process_qc_scan(
        cls,
        po_id: uuid.UUID,
        qc_data: list[dict],  # [{"line_item_id": str, "passed_qty": int, "failed_qty": int, "notes": str}]
        actor_id: Optional[uuid.UUID] = None,
    ) -> dict:
        """
        Processes inline QC scan results for a received PO.

        For each line item with passed_qty > 0:
          → Increments stock via inventory.StockLedgerService
          → Recalculates MAC via inventory.ValuationEngine

        Returns summary of items processed.
        """
        from apps.inventory.services import StockLedgerService, ValuationEngine

        po = PurchaseOrder.objects.select_for_update().get(id=po_id)
        if po.status not in (POStatus.IN_TRANSIT, POStatus.RECEIVED):
            raise ValueError(
                f"QC scan can only be performed on IN_TRANSIT or RECEIVED POs. "
                f"Current status: '{po.status}'."
            )

        summary = {"lines_processed": 0, "passed_total": 0, "failed_total": 0}
        has_failures = False

        for scan in qc_data:
            line_id = uuid.UUID(str(scan["line_item_id"]))
            passed_qty = int(scan.get("passed_qty", 0))
            failed_qty = int(scan.get("failed_qty", 0))
            notes = scan.get("notes", "")

            line = POLineItem.objects.select_for_update().get(id=line_id, po=po)

            # Update QC fields on the line item.
            line.qc_passed_qty = passed_qty
            line.qc_failed_qty = failed_qty
            line.qc_notes = notes
            line.qc_completed_at = timezone.now()
            line.save(update_fields=[
                "qc_passed_qty", "qc_failed_qty", "qc_notes", "qc_completed_at"
            ])

            # Increment stock for passed items.
            if passed_qty > 0:
                StockLedgerService.increment_stock(
                    product_id=line.product_id,
                    qty=passed_qty,
                    reference_module="procurement",
                    reference_id=po.id,
                    unit_cost=line.unit_cost,
                    notes=f"QC pass: PO#{str(po_id)[:8]} line#{str(line_id)[:8]}",
                    actor_id=actor_id,
                )
                # Recalculate Moving Average Cost.
                ValuationEngine.recalculate_mac(
                    product_id=line.product_id,
                    received_qty=passed_qty,
                    new_unit_cost=line.unit_cost,
                )

            if failed_qty > 0:
                has_failures = True

            summary["lines_processed"] += 1
            summary["passed_total"] += passed_qty
            summary["failed_total"] += failed_qty

        # Transition PO to RECEIVED (or QC_FAILED if all items failed).
        final_status = POStatus.QC_FAILED if (summary["passed_total"] == 0 and has_failures) else POStatus.RECEIVED
        po.status = final_status
        po.save(update_fields=["status"])

        logger.info(
            "QC scan complete for PO '%s': passed=%d, failed=%d, status=%s.",
            po_id,
            summary["passed_total"],
            summary["failed_total"],
            final_status,
        )
        summary["final_po_status"] = final_status
        return summary
