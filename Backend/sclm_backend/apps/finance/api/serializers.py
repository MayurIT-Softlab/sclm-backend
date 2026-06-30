"""
apps.finance.api.serializers
"""
from rest_framework import serializers
from apps.finance.models import ChartOfAccounts, JournalEntry, JournalLine


class ChartOfAccountsSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChartOfAccounts
        fields = [
            "id",
            "account_code",
            "account_name",
            "account_type",
            "description",
            "is_active",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class JournalLineSerializer(serializers.ModelSerializer):
    account_code = serializers.CharField(source="account.account_code", read_only=True)
    account_name = serializers.CharField(source="account.account_name", read_only=True)

    class Meta:
        model = JournalLine
        fields = [
            "id",
            "entry",
            "account",
            "account_code",
            "account_name",
            "debit",
            "credit",
            "memo",
        ]
        read_only_fields = ["id", "account_code", "account_name"]


class JournalEntrySerializer(serializers.ModelSerializer):
    lines = JournalLineSerializer(many=True, read_only=True)
    debit_total = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True,
                                           source="get_debit_total")
    credit_total = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True,
                                            source="get_credit_total")
    is_balanced = serializers.BooleanField(read_only=True)

    class Meta:
        model = JournalEntry
        fields = [
            "id",
            "entry_type",
            "reference_module",
            "reference_id",
            "description",
            "posted_by_actor_id",
            "timestamp",
            "is_reconciled",
            "debit_total",
            "credit_total",
            "is_balanced",
            "lines",
        ]
        read_only_fields = [
            "id",
            "posted_by_actor_id",
            "timestamp",
            "debit_total",
            "credit_total",
            "is_balanced",
        ]
