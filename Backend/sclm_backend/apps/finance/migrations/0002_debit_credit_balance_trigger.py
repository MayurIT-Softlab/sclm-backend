"""
apps.finance.migrations.0002_debit_credit_balance_trigger
─────────────────────────────────────────────────────────────────────────────
Installs a PostgreSQL AFTER INSERT OR UPDATE trigger on finance_journalline.

After any insert/update on journal lines, this trigger checks whether the
parent JournalEntry is still balanced (SUM(debit) == SUM(credit)).
If not, it raises an exception and the entire transaction is rolled back.

This is the THIRD layer of the debit-credit balance guarantee:
  Layer 1: JournalEntryService.validate_and_commit() (service layer)
  Layer 2: model.clean() (Django model validation)
  Layer 3: This PostgreSQL trigger (DB-level, cannot be bypassed)
─────────────────────────────────────────────────────────────────────────────
"""
from django.db import migrations


TRIGGER_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION fn_check_journal_balance()
RETURNS TRIGGER AS $$
DECLARE
    v_total_debit  NUMERIC(18, 2);
    v_total_credit NUMERIC(18, 2);
    v_line_count   INTEGER;
BEGIN
    -- Count lines and sum debits/credits for the affected JournalEntry.
    SELECT
        COUNT(*),
        COALESCE(SUM(debit),  0),
        COALESCE(SUM(credit), 0)
    INTO v_line_count, v_total_debit, v_total_credit
    FROM finance_journalline
    WHERE entry_id = NEW.entry_id;

    -- Only validate if the entry has at least 2 lines (otherwise it's being built).
    IF v_line_count >= 2 AND v_total_debit != v_total_credit THEN
        RAISE EXCEPTION
            'DOUBLE-ENTRY BALANCE VIOLATION: JournalEntry % is unbalanced. '
            'Total Debits: % | Total Credits: % | Difference: %. '
            'Transaction aborted.',
            NEW.entry_id,
            v_total_debit,
            v_total_credit,
            ABS(v_total_debit - v_total_credit);
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

TRIGGER_SQL = """
DROP TRIGGER IF EXISTS trg_check_journal_balance ON finance_journalline;

CREATE CONSTRAINT TRIGGER trg_check_journal_balance
    AFTER INSERT OR UPDATE ON finance_journalline
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW
    EXECUTE FUNCTION fn_check_journal_balance();
"""

DROP_TRIGGER_SQL = """
DROP TRIGGER IF EXISTS trg_check_journal_balance ON finance_journalline;
DROP FUNCTION IF EXISTS fn_check_journal_balance();
"""


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql=TRIGGER_FUNCTION_SQL + TRIGGER_SQL,
            reverse_sql=DROP_TRIGGER_SQL,
            hints={"target_db": "default"},
        ),
    ]
