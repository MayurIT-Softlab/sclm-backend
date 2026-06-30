from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import BinLocationViewSet, InventoryPositionViewSet

router = DefaultRouter()
router.register("bins", BinLocationViewSet, basename="bin")
router.register("positions", InventoryPositionViewSet, basename="inventory-position")

app_name = "warehouse"
urlpatterns = [path("", include(router.urls))]
