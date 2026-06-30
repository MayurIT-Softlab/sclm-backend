from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import DemandPredictionViewSet

router = DefaultRouter()
router.register("predictions", DemandPredictionViewSet, basename="prediction")

app_name = "forecasting"
urlpatterns = [path("", include(router.urls))]
