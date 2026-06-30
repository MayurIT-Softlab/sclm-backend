"""
apps.audit_ledger.api.views
GET /api/v1/audit-ledger/commits/     [ADMIN only]
GET /api/v1/audit-ledger/commits/{id}/ [ADMIN only]
"""
from rest_framework import viewsets, filters
from rest_framework.permissions import IsAuthenticated
from apps.audit_ledger.models import AuditCommit
from apps.audit_ledger.api.serializers import AuditCommitSerializer
from apps.users.permissions import IsAdminRole
from core.pagination import StandardResultsPagination


class AuditCommitViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Immutable audit trail. GET-only. ADMIN role exclusively.

    Supports filtering by:
      ?table_name=inventory_productsku
      ?action=UPDATE
      ?actor_id=<uuid>
    """
    queryset = AuditCommit.objects.all().order_by("-timestamp")
    serializer_class = AuditCommitSerializer
    permission_classes = [IsAuthenticated, IsAdminRole]
    pagination_class = StandardResultsPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["table_name", "action"]
    ordering_fields = ["timestamp", "action", "table_name"]

    def get_queryset(self):
        qs = super().get_queryset()
        table_name = self.request.query_params.get("table_name")
        action = self.request.query_params.get("action")
        actor_id = self.request.query_params.get("actor_id")
        record_id = self.request.query_params.get("record_id")
        if table_name:
            qs = qs.filter(table_name=table_name)
        if action:
            qs = qs.filter(action=action.upper())
        if actor_id:
            qs = qs.filter(actor_id=actor_id)
        if record_id:
            qs = qs.filter(record_id=record_id)
        return qs
