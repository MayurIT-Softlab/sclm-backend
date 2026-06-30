from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import VehicleViewSet, DispatchRouteViewSet, RouteStopViewSet

router = DefaultRouter()
router.register("vehicles", VehicleViewSet, basename="vehicle")
router.register("routes", DispatchRouteViewSet, basename="dispatch-route")
router.register("route-stops", RouteStopViewSet, basename="route-stop")

app_name = "transportation"
urlpatterns = [path("", include(router.urls))]
