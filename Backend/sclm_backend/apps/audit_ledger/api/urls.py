from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import AuditCommitViewSet

router = DefaultRouter()
router.register("commits", AuditCommitViewSet, basename="audit-commit")

app_name = "audit_ledger"
urlpatterns = [path("", include(router.urls))]
