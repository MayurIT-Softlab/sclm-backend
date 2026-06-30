"""
apps.subscriptions.api.views
─────────────────────────────────────────────────────────────────────────────
CurrentPlanView    GET  /api/v1/subscriptions/current-plan/     [ADMIN]
StripeWebhookView  POST /api/v1/subscriptions/webhooks/stripe/  [System]
─────────────────────────────────────────────────────────────────────────────
"""
import json
import logging
from django.conf import settings
from django.db import connection
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated

from apps.users.permissions import IsAdminRole
from apps.subscriptions.models import Client
from apps.subscriptions.services import StripeWebhookReceiver
from .serializers import ClientPlanSerializer

logger = logging.getLogger(__name__)


class CurrentPlanView(APIView):
    """
    GET /api/v1/subscriptions/current-plan/
    Returns active plan tier, limits, and expiration for the current tenant.
    Restricted to ADMIN role only.
    """
    permission_classes = [IsAuthenticated, IsAdminRole]

    def get(self, request, *args, **kwargs):
        tenant_id = getattr(request, "tenant_id", None)
        if not tenant_id:
            return Response(
                {"code": "NO_TENANT", "message": "No tenant context found."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Query the public schema for the Client record.
        connection.set_schema_to_public()
        try:
            client = Client.objects.get(id=tenant_id)
        except Client.DoesNotExist:
            return Response(
                {"code": "NOT_FOUND", "message": "Tenant not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = ClientPlanSerializer(client)
        return Response(serializer.data, status=status.HTTP_200_OK)


class StripeWebhookView(APIView):
    """
    POST /api/v1/subscriptions/webhooks/stripe/

    Receives asynchronous payment events from Stripe.
    Validates the webhook signature before processing any event.
    This endpoint is PUBLIC — it does not require a JWT.
    """
    permission_classes = [AllowAny]
    authentication_classes = []  # No JWT auth for webhooks

    def post(self, request, *args, **kwargs):
        payload = request.body
        sig_header = request.headers.get("Stripe-Signature", "")
        webhook_secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", "")

        if not StripeWebhookReceiver.verify_signature(payload, sig_header, webhook_secret):
            logger.warning("Stripe webhook: invalid signature.")
            return Response(
                {"detail": "Invalid Stripe signature."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            return Response(
                {"detail": "Invalid JSON payload."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        event_type = event.get("type", "")
        tenant_schema = event.get("data", {}).get("object", {}).get("metadata", {}).get(
            "tenant_schema", ""
        )

        if event_type == "invoice.payment_succeeded":
            StripeWebhookReceiver.handle_payment_succeeded(tenant_schema)
        elif event_type in ("invoice.payment_failed", "customer.subscription.deleted"):
            StripeWebhookReceiver.handle_payment_failed(tenant_schema)
        else:
            logger.debug("Unhandled Stripe event type: '%s'.", event_type)

        # Always return 200 to Stripe to acknowledge receipt.
        return Response({"received": True}, status=status.HTTP_200_OK)
