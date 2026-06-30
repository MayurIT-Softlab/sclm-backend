"""
apps.subscriptions.api.urls
All routes are prefixed with /api/v1/subscriptions/ in urls_public.py.
"""
from django.urls import path
from .views import CurrentPlanView, StripeWebhookView

app_name = "subscriptions"

urlpatterns = [
    path("current-plan/", CurrentPlanView.as_view(), name="current-plan"),
    path("webhooks/stripe/", StripeWebhookView.as_view(), name="stripe-webhook"),
]
