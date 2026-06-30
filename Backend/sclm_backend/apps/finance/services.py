"""
apps.finance.services
─────────────────────────────────────────────────────────────────────────────
JournalEntryService   — The most secure function in the app.
                        Validates SUM(debits) == SUM(credits) BEFORE committing.
                        If imbalanced → raises exception → transaction rollback.

BankFeedReconciliation — Matches Plaid bank feed to internal journal entries.

Convenience helpers called by other modules:
  encumber_budget()      → called by procurement on PO APPROVED
  recognize_revenue()    → called by logistics on ePOD DELIVERED
  write_off_asset()      → called by returns on SCRAP disposition
─────────────────────────────────────────────────────────────────────────────
"""
import uuid
import logging
from decimal import Decimal
from typing import Optional

from django.db import transaction

logger = logging.getLogger(__name__)

# Well-known account codes (must exist in ChartOfAccounts for the tenant).
# These constants are used by the service helpers below.
ACCOUNTS_RECEIVABLE_CODE = "1100"
INVENTORY_ASSET_CODE = "1200"
ACCOUNTS_PAYABLE_CODE = "2100"
REVENUE_CODE = "4100"
COGS_CODE = "5100"
ASSET_WRITE_OFF_CODE = "5200"  # Loss / Write-Off Expense


class JournalEntryService:
    """
    The atomic double-entry ledger writer.

    Usage pattern:
        lines = [
            {"account_code": "1100", "debit": Decimal("1200.00"), "credit": Decimal("0")},
            {"account_code": "1200", "debit": Decimal("0"), "credit": Decimal("1200.00")},
        ]
        JournalEntryService.create(
            entry_type="REVENUE_RECOGNITION",
            reference_module="logistics",
            reference_id=sales_order.id,
            lines=lines,
            actor_id=user.id,
        )

    INVARIANT: SUM(debits) == SUM(credits) or the transaction ABORTS.
    """

    @classmethod
    @transaction.atomic
    def create(
        cls,
        entry_type: str,
        reference_module: str,
        reference_id: uuid.UUID,
        lines: list[dict],
        description: str = "",
        actor_id: Optional[uuid.UUID] = None,
    ) -> "JournalEntry":  # type: ignore
        """
        Creates a balanced JournalEntry with all its JournalLines atomically.

        Args:
            entry_type:       JournalEntry.EntryType choice value.
            reference_module: Module that triggered this entry ('logistics', etc.)
            reference_id:     UUID of the source document.
            lines:            List of dicts: [{"account_code": str, "debit": Decimal, "credit": Decimal, "memo": str}]
            description:      Human-readable description.
            actor_id:         UUID of the GlobalUser initiating this entry.

        Raises:
            ValueError: If lines are unbalanced or an account code doesn't exist.
        """
        from apps.finance.models import JournalEntry, JournalLine, ChartOfAccounts

        # ── LAYER 1: Service-level balance validation ──────────────────────
        cls._validate_balance(lines)

        # ── Create header ──────────────────────────────────────────────────
        entry = JournalEntry.objects.create(
            entry_type=entry_type,
            reference_module=reference_module,
            reference_id=reference_id,
            description=description,
            posted_by_actor_id=actor_id,
        )

        # ── Resolve account codes → account PKs ───────────────────────────
        codes = [line["account_code"] for line in lines]
        accounts = ChartOfAccounts.objects.filter(
            account_code__in=codes,
            is_active=True,
        ).in_bulk(field_name="account_code")

        missing = set(codes) - set(accounts.keys())
        if missing:
            raise ValueError(
                f"Chart of Accounts: account codes {missing} not found or inactive. "
                "Cannot create journal entry. Transaction aborted."
            )

        # ── Create lines ───────────────────────────────────────────────────
        journal_lines = [
            JournalLine(
                entry=entry,
                account=accounts[line["account_code"]],
                debit=Decimal(str(line.get("debit", "0"))),
                credit=Decimal(str(line.get("credit", "0"))),
                memo=line.get("memo", ""),
            )
            for line in lines
        ]
        JournalLine.objects.bulk_create(journal_lines)

        # ── LAYER 2: Post-insert DB trigger validates balance ──────────────
        # (The DEFERRABLE CONSTRAINT TRIGGER fires at transaction end)

        logger.info(
            "JournalEntry created: id=%s type=%s ref=%s:%s total=%.2f",
            entry.id,
            entry_type,
            reference_module,
            reference_id,
            sum(Decimal(str(l.get("debit", 0))) for l in lines),
        )
        return entry

    @classmethod
    def _validate_balance(cls, lines: list[dict]) -> None:
        """
        Layer 1 validation: SUM(debits) == SUM(credits).
        Raises ValueError before touching the DB if imbalanced.
        """
        if not lines:
            raise ValueError("A journal entry must have at least 2 lines.")
        if len(lines) < 2:
            raise ValueError(
                "A journal entry requires at least one debit and one credit line."
            )

        total_debit = sum(Decimal(str(l.get("debit", 0))) for l in lines)
        total_credit = sum(Decimal(str(l.get("credit", 0))) for l in lines)

        if total_debit != total_credit:
            raise ValueError(
                f"DOUBLE-ENTRY BALANCE VIOLATION: "
                f"Total Debits={total_debit} ≠ Total Credits={total_credit}. "
                f"Difference: {abs(total_debit - total_credit)}. "
                "Transaction aborted."
            )
        if total_debit == Decimal("0"):
            raise ValueError("Journal entry cannot have zero total value.")

    # ── Convenience helpers ────────────────────────────────────────────────

    @classmethod
    def encumber_budget(
        cls,
        po_id: uuid.UUID,
        total_amount: Decimal,
        actor_id: Optional[uuid.UUID] = None,
    ) -> "JournalEntry":  # type: ignore
        """
        Called atomically by procurement.POStateMachineService when a PO
        transitions from DRAFT → APPROVED.

        Accounting entry:
          DR Purchases / COGS (5100)          [expense recognised]
          CR Accounts Payable (2100)           [we owe the vendor]
        """
        lines = [
            {
                "account_code": COGS_CODE,
                "debit": total_amount,
                "credit": Decimal("0"),
                "memo": f"Budget encumbrance for PO {str(po_id)[:8]}",
            },
            {
                "account_code": ACCOUNTS_PAYABLE_CODE,
                "debit": Decimal("0"),
                "credit": total_amount,
                "memo": f"Vendor payable for PO {str(po_id)[:8]}",
            },
        ]
        return cls.create(
            entry_type="BUDGET_ENCUMBRANCE",
            reference_module="procurement",
            reference_id=po_id,
            lines=lines,
            description=f"Budget encumbrance: PO #{str(po_id)[:8]}",
            actor_id=actor_id,
        )

    @classmethod
    def recognize_revenue(
        cls,
        sales_order_id: uuid.UUID,
        revenue_amount: Decimal,
        inventory_cost: Decimal,
        actor_id: Optional[uuid.UUID] = None,
    ) -> "JournalEntry":  # type: ignore
        """
        Called atomically by logistics.ePODCaptureService on DELIVERED.

        Accounting entry (two-leg approach):
          Leg 1 — Revenue recognition:
            DR Accounts Receivable (1100)     [customer owes us]
            CR Revenue (4100)                 [we earned revenue]
          Leg 2 — Inventory reduction:
            DR Cost of Goods Sold (5100)      [cost of goods leaves]
            CR Inventory Asset (1200)         [inventory value leaves]

        If inventory_cost > 0, both legs are combined in one entry.
        """
        lines = [
            # Revenue recognition
            {
                "account_code": ACCOUNTS_RECEIVABLE_CODE,
                "debit": revenue_amount,
                "credit": Decimal("0"),
                "memo": f"Revenue: SO#{str(sales_order_id)[:8]}",
            },
            {
                "account_code": REVENUE_CODE,
                "debit": Decimal("0"),
                "credit": revenue_amount,
                "memo": f"Revenue earned: SO#{str(sales_order_id)[:8]}",
            },
        ]

        if inventory_cost > Decimal("0"):
            lines += [
                {
                    "account_code": COGS_CODE,
                    "debit": inventory_cost,
                    "credit": Decimal("0"),
                    "memo": f"COGS: SO#{str(sales_order_id)[:8]}",
                },
                {
                    "account_code": INVENTORY_ASSET_CODE,
                    "debit": Decimal("0"),
                    "credit": inventory_cost,
                    "memo": f"Inventory reduction: SO#{str(sales_order_id)[:8]}",
                },
            ]

        return cls.create(
            entry_type="REVENUE_RECOGNITION",
            reference_module="logistics",
            reference_id=sales_order_id,
            lines=lines,
            description=f"Revenue recognition for Sales Order #{str(sales_order_id)[:8]}",
            actor_id=actor_id,
        )

    @classmethod
    def write_off_asset(
        cls,
        rma_id: uuid.UUID,
        write_off_amount: Decimal,
        actor_id: Optional[uuid.UUID] = None,
    ) -> "JournalEntry":  # type: ignore
        """
        Called by returns.RMATriageService on SCRAP disposition.

        Accounting entry:
          DR Asset Write-Off Expense (5200)   [loss recognised]
          CR Inventory Asset (1200)           [inventory value removed]
        """
        lines = [
            {
                "account_code": ASSET_WRITE_OFF_CODE,
                "debit": write_off_amount,
                "credit": Decimal("0"),
                "memo": f"Asset write-off for RMA #{str(rma_id)[:8]}",
            },
            {
                "account_code": INVENTORY_ASSET_CODE,
                "debit": Decimal("0"),
                "credit": write_off_amount,
                "memo": f"Inventory scrapped: RMA #{str(rma_id)[:8]}",
            },
        ]
        return cls.create(
            entry_type="ASSET_WRITE_OFF",
            reference_module="returns",
            reference_id=rma_id,
            lines=lines,
            description=f"Asset write-off for scrapped RMA #{str(rma_id)[:8]}",
            actor_id=actor_id,
        )


class BankFeedReconciliation:
    """
    Pulls the last 24 hours of bank statements via the Plaid API and
    matches them to internal JournalEntries by amount + PO reference.
    Called by POST /finance/bank-feed/sync/ [Accountant].
    """

    @classmethod
    def sync(cls, actor_id: Optional[uuid.UUID] = None) -> dict:
        """
        Placeholder for Plaid API integration.
        Step 6 will wire the actual Plaid HTTP client call here.
        Returns a summary of matched/unmatched transactions.
        """
        logger.info("BankFeedReconciliation.sync() called by actor: %s", actor_id)
        # TODO (Step 6): Implement Plaid API client call
        # plaid_transactions = PlaidClient.get_transactions(days=1)
        # for txn in plaid_transactions:
        #     cls._match_to_journal_entry(txn)
        return {
            "synced": 0,
            "matched": 0,
            "unmatched": 0,
            "message": "Plaid integration placeholder — implement in Step 6.",
        }
