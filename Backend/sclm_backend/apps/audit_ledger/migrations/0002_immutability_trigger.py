"""
apps.audit_ledger.migrations.0002_immutability_trigger
─────────────────────────────────────────────────────────────────────────────
Installs a PostgreSQL BEFORE UPDATE OR DELETE trigger on audit_ledger_auditcommit.

This trigger is the primary guard against mutation. Even if a developer
bypasses the Django model layer (e.g., via raw SQL), the DB will raise
an exception and abort the transaction.

The trigger raises: "audit_ledger_auditcommit is immutable. Updates and
deletes are permanently forbidden on this table."
─────────────────────────────────────────────────────────────────────────────
"""
from django.db import migrations


TRIGGER_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION fn_prevent_audit_commit_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        'audit_ledger_auditcommit is IMMUTABLE. '
        'UPDATE and DELETE operations are permanently forbidden. '
        'Record ID: % | Action attempted: %',
        OLD.id,
        TG_OP;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
"""

TRIGGER_SQL = """
DROP TRIGGER IF EXISTS trg_prevent_audit_commit_mutation
    ON audit_ledger_auditcommit;

CREATE TRIGGER trg_prevent_audit_commit_mutation
    BEFORE UPDATE OR DELETE ON audit_ledger_auditcommit
    FOR EACH ROW
    EXECUTE FUNCTION fn_prevent_audit_commit_mutation();
"""

DROP_TRIGGER_SQL = """
DROP TRIGGER IF EXISTS trg_prevent_audit_commit_mutation
    ON audit_ledger_auditcommit;
DROP FUNCTION IF EXISTS fn_prevent_audit_commit_mutation();
"""


class Migration(migrations.Migration):

    dependencies = [
        ("audit_ledger", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql=TRIGGER_FUNCTION_SQL + TRIGGER_SQL,
            reverse_sql=DROP_TRIGGER_SQL,
            hints={"target_db": "default"},
        ),
    ]
