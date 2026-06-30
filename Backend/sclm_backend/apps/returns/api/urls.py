from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import RMAClaimViewSet

router = DefaultRouter()
router.register("rma-claims", RMAClaimViewSet, basename="rma-claim")

app_name = "returns"
urlpatterns = [path("", include(router.urls))]
