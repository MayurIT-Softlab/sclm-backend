"""
apps.finance.api.views
GET/POST   /api/v1/finance/accounts/                  [ACCOUNTANT, ADMIN]
GET        /api/v1/finance/journal-entries/           [ACCOUNTANT, ADMIN]
GET        /api/v1/finance/journal-entries/{id}/      [ACCOUNTANT, ADMIN]
POST       /api/v1/finance/journal-entries/{id}/reconcile/  [ACCOUNTANT, ADMIN]
GET        /api/v1/finance/journal-lines/             [ACCOUNTANT, ADMIN]
"""
from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.finance.models import ChartOfAccounts, JournalEntry, JournalLine
from apps.finance.api.serializers import (
    ChartOfAccountsSerializer,
    JournalEntrySerializer,
    JournalLineSerializer,
)
from apps.users.permissions import IsAccountant
from core.pagination import StandardResultsPagination


class ChartOfAccountsViewSet(viewsets.ModelViewSet):
    """
    Master list of GL accounts.
    Accountant can create new accounts; Enterprise Admin manages existing ones.
    """
    queryset = ChartOfAccounts.objects.all().order_by("account_code")
    serializer_class = ChartOfAccountsSerializer
    permission_classes = [IsAuthenticated, IsAccountant]
    pagination_class = StandardResultsPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["account_code", "account_name", "account_type"]
    ordering_fields = ["account_code", "account_type"]

    def get_queryset(self):
        qs = super().get_queryset()
        account_type = self.request.query_params.get("account_type")
        is_active = self.request.query_params.get("is_active")
        if account_type:
            qs = qs.filter(account_type=account_type.upper())
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() == "true")
        return qs


class JournalEntryViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only view of the double-entry journal.

    Journal entries are NEVER created via the API directly —
    they are created by the service layer (revenue recognition, PO encumbrance,
    asset write-off). This ensures the double-entry invariant is always enforced.

    Exception: Manual Adjustment entries can be created by ADMIN via a separate
    management command or Django Admin.
    """
    queryset = (
        JournalEntry.objects
        .prefetch_related("lines__account")
        .order_by("-timestamp")
    )
    serializer_class = JournalEntrySerializer
    permission_classes = [IsAuthenticated, IsAccountant]
    pagination_class = StandardResultsPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["entry_type", "reference_module", "description"]
    ordering_fields = ["timestamp", "entry_type"]

    def get_queryset(self):
        qs = super().get_queryset()
        entry_type = self.request.query_params.get("entry_type")
        ref_module = self.request.query_params.get("reference_module")
        ref_id = self.request.query_params.get("reference_id")
        is_reconciled = self.request.query_params.get("is_reconciled")
        if entry_type:
            qs = qs.filter(entry_type=entry_type.upper())
        if ref_module:
            qs = qs.filter(reference_module=ref_module)
        if ref_id:
            qs = qs.filter(reference_id=ref_id)
        if is_reconciled is not None:
            qs = qs.filter(is_reconciled=is_reconciled.lower() == "true")
        return qs

    @action(detail=True, methods=["post"])
    def reconcile(self, request, pk=None):
        """
        POST /api/v1/finance/journal-entries/{id}/reconcile/
        Marks a journal entry as reconciled (bank feed matched).
        """
        entry = self.get_object()
        if entry.is_reconciled:
            return Response(
                {"detail": "This journal entry is already reconciled."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        entry.is_reconciled = True
        entry.save(update_fields=["is_reconciled"])
        return Response(self.get_serializer(entry).data)


class JournalLineViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only view of individual journal lines (debit/credit entries)."""
    queryset = (
        JournalLine.objects
        .select_related("entry", "account")
        .order_by("entry__timestamp")
    )
    serializer_class = JournalLineSerializer
    permission_classes = [IsAuthenticated, IsAccountant]
    pagination_class = StandardResultsPagination

    def get_queryset(self):
        qs = super().get_queryset()
        entry_id = self.request.query_params.get("entry_id")
        account_id = self.request.query_params.get("account_id")
        if entry_id:
            qs = qs.filter(entry_id=entry_id)
        if account_id:
            qs = qs.filter(account_id=account_id)
        return qs
