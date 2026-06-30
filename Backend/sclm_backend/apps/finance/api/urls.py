from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ChartOfAccountsViewSet, JournalEntryViewSet, JournalLineViewSet

router = DefaultRouter()
router.register("accounts", ChartOfAccountsViewSet, basename="chart-of-accounts")
router.register("journal-entries", JournalEntryViewSet, basename="journal-entry")
router.register("journal-lines", JournalLineViewSet, basename="journal-line")

app_name = "finance"
urlpatterns = [path("", include(router.urls))]
