from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ProductSKUViewSet, StockLedgerViewSet

router = DefaultRouter()
router.register("products", ProductSKUViewSet, basename="product")
router.register("ledger", StockLedgerViewSet, basename="ledger")

app_name = "inventory"
urlpatterns = [path("", include(router.urls))]
