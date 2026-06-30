from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import InboundContainerViewSet, SalesOrderViewSet, SalesOrderItemViewSet

router = DefaultRouter()
router.register("containers", InboundContainerViewSet, basename="container")
router.register("sales-orders", SalesOrderViewSet, basename="sales-order")
router.register("sales-order-items", SalesOrderItemViewSet, basename="sales-order-item")

app_name = "logistics"
urlpatterns = [path("", include(router.urls))]
