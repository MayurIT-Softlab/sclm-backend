"""
apps.finance.models
Schema: tenant
─────────────────────────────────────────────────────────────────────────────
ChartOfAccounts — The corporate account taxonomy (Asset, Liability, etc.)
JournalEntry    — The double-entry header record.
JournalLine     — Individual debit/credit lines on a JournalEntry.

CRITICAL CONSTRAINT:
  The DB-level invariant SUM(debit) == SUM(credit) per JournalEntry is
  enforced by:
    1. JournalEntryService.validate_and_commit() (service layer)
    2. A PostgreSQL AFTER INSERT OR UPDATE trigger on journal_line
       (see migration 0002_debit_credit_balance_trigger.py)
  Both guards must pass. If the finance step fails → atomic rollback.
─────────────────────────────────────────────────────────────────────────────
"""
import uuid
from decimal import Decimal
from django.db import models
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError


class AccountType(models.TextChoices):
    ASSET = "ASSET", "Asset"
    LIABILITY = "LIABILITY", "Liability"
    EQUITY = "EQUITY", "Equity"
    REVENUE = "REVENUE", "Revenue"
    EXPENSE = "EXPENSE", "Expense"


class ChartOfAccounts(models.Model):
    """
    The master list of financial accounts (the ledger taxonomy).

    Examples:
      1100 — Accounts Receivable (ASSET)
      1200 — Inventory Asset (ASSET)
      2100 — Accounts Payable (LIABILITY)
      4100 — Revenue (REVENUE)
      5100 — Cost of Goods Sold (EXPENSE)
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account_code = models.CharField(
        max_length=20,
        unique=True,
        db_index=True,
        help_text="Numeric or alphanumeric account code (e.g., '1100', 'AR-USD').",
    )
    account_name = models.CharField(max_length=255)
    account_type = models.CharField(
        max_length=15,
        choices=AccountType.choices,
        db_index=True,
    )
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(
        default=True,
        help_text="Inactive accounts cannot receive new journal lines.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "finance"
        verbose_name = "Chart of Accounts"
        verbose_name_plural = "Chart of Accounts"
        ordering = ["account_code"]

    def __str__(self) -> str:
        return f"{self.account_code} — {self.account_name} [{self.account_type}]"


class JournalEntry(models.Model):
    """
    The header record for a double-entry bookkeeping transaction.

    One JournalEntry always has ≥ 2 JournalLines.
    INVARIANT: SUM(JournalLine.debit) == SUM(JournalLine.credit)
    This is enforced by JournalEntryService BEFORE committing to DB.

    reference_module + reference_id form a polymorphic link to the
    source business event (e.g., reference_module='logistics',
    reference_id=<SalesOrder UUID>).
    """
    class EntryType(models.TextChoices):
        REVENUE_RECOGNITION = "REVENUE_RECOGNITION", "Revenue Recognition (Delivery)"
        BUDGET_ENCUMBRANCE = "BUDGET_ENCUMBRANCE", "Budget Encumbrance (PO Approved)"
        ASSET_WRITE_OFF = "ASSET_WRITE_OFF", "Asset Write-Off (Scrap)"
        BANK_RECONCILIATION = "BANK_RECONCILIATION", "Bank Reconciliation"
        MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT", "Manual Adjustment"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entry_type = models.CharField(
        max_length=25,
        choices=EntryType.choices,
        db_index=True,
    )
    reference_module = models.CharField(
        max_length=30,
        db_index=True,
        help_text="Which module triggered this journal entry (e.g., 'logistics').",
    )
    reference_id = models.UUIDField(
        db_index=True,
        help_text="UUID of the source document (SalesOrder, PO, RMA, etc.).",
    )
    description = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Human-readable description of the transaction.",
    )
    # Cross-schema: UUID of the actor who triggered this entry.
    posted_by_actor_id = models.UUIDField(
        null=True,
        blank=True,
        help_text="UUID of the GlobalUser who initiated this journal entry.",
    )
    timestamp = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )
    is_reconciled = models.BooleanField(
        default=False,
        help_text="True when BankFeedReconciliation has matched this entry.",
    )

    class Meta:
        app_label = "finance"
        verbose_name = "Journal Entry"
        verbose_name_plural = "Journal Entries"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(
                fields=["reference_module", "reference_id"],
                name="je_ref_idx",
            ),
            models.Index(fields=["timestamp"], name="je_ts_idx"),
        ]

    def __str__(self) -> str:
        return (
            f"JE#{str(self.id)[:8]} [{self.entry_type}] "
            f"{self.reference_module}:{str(self.reference_id)[:8]}"
        )

    def get_debit_total(self) -> Decimal:
        """Returns the sum of all debit amounts on this entry."""
        return self.lines.aggregate(
            total=models.Sum("debit")
        )["total"] or Decimal("0")

    def get_credit_total(self) -> Decimal:
        """Returns the sum of all credit amounts on this entry."""
        return self.lines.aggregate(
            total=models.Sum("credit")
        )["total"] or Decimal("0")

    def is_balanced(self) -> bool:
        """True if SUM(debit) == SUM(credit). Checked by JournalEntryService."""
        return self.get_debit_total() == self.get_credit_total()


class JournalLine(models.Model):
    """
    A single debit OR credit line on a JournalEntry.

    Invariant (enforced by service + DB trigger):
      For a given entry_id, SUM(debit) == SUM(credit).
      A line has debit > 0 OR credit > 0, never both.

    Example — Revenue recognition on delivery:
      Line 1: Debit  Accounts Receivable (1100)  $1,200
      Line 2: Credit Inventory Asset (1200)       $1,200
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.CASCADE,
        related_name="lines",
        db_index=True,
    )
    account = models.ForeignKey(
        ChartOfAccounts,
        on_delete=models.PROTECT,
        related_name="journal_lines",
        db_index=True,
    )
    debit = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Debit amount. Exactly one of debit/credit should be > 0.",
    )
    credit = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Credit amount. Exactly one of debit/credit should be > 0.",
    )
    memo = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Line-level description (e.g., 'Invoice #12345 for SKU-ELEC-001').",
    )

    class Meta:
        app_label = "finance"
        verbose_name = "Journal Line"
        verbose_name_plural = "Journal Lines"
        constraints = [
            # Enforce that a line cannot have both debit AND credit > 0.
            models.CheckConstraint(
                condition=(
                    models.Q(debit=0) | models.Q(credit=0)
                ),
                name="journal_line_not_both_debit_and_credit",
            ),
            # At least one of debit or credit must be > 0.
            models.CheckConstraint(
                condition=(
                    models.Q(debit__gt=0) | models.Q(credit__gt=0)
                ),
                name="journal_line_at_least_one_nonzero",
            ),
        ]

    def __str__(self) -> str:
        if self.debit > 0:
            return f"DR {self.account.account_code} ${self.debit}"
        return f"CR {self.account.account_code} ${self.credit}"

    def clean(self):
        """Model-level validation as a third layer of safety."""
        super().clean()
        if self.debit > 0 and self.credit > 0:
            raise ValidationError(
                "A journal line cannot have both debit and credit amounts."
            )
        if self.debit == 0 and self.credit == 0:
            raise ValidationError(
                "A journal line must have either a debit or a credit amount."
            )
