from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PurchaseOrderViewSet, POLineItemViewSet

router = DefaultRouter()
router.register("purchase-orders", PurchaseOrderViewSet, basename="purchase-order")
router.register("line-items", POLineItemViewSet, basename="po-line-item")

app_name = "procurement"
urlpatterns = [path("", include(router.urls))]
