"""
apps.subscriptions.services
LicenseValidatorService — Checks tenant plan tier limits.
StripeWebhookReceiver   — Handles payment events from Stripe.
"""
import logging
import hashlib
import hmac
from django.conf import settings
from django.utils import timezone
from .models import Client, PlanTier

logger = logging.getLogger(__name__)


class LicenseValidatorService:
    """
    Checks whether a tenant has exceeded their paid plan tier limits.
    Called before write operations that create new resources
    (e.g., adding a 6th warehouse on a 5-warehouse STARTER plan).
    """

    # Maximum warehouse count per plan tier.
    WAREHOUSE_LIMITS = {
        PlanTier.STARTER: 2,
        PlanTier.PROFESSIONAL: 10,
        PlanTier.ENTERPRISE: 999,
    }

    @classmethod
    def assert_tenant_active(cls, tenant: Client) -> None:
        """Raise ValueError if the tenant subscription is inactive or expired."""
        if not tenant.is_active:
            raise ValueError(
                f"Tenant '{tenant.company_name}' subscription is inactive. "
                "Please renew your plan."
            )
        if tenant.subscription_expires_at and tenant.subscription_expires_at < timezone.now():
            raise ValueError(
                f"Tenant '{tenant.company_name}' subscription expired on "
                f"{tenant.subscription_expires_at}. Please renew your plan."
            )

    @classmethod
    def assert_warehouse_limit(cls, tenant: Client, current_count: int) -> None:
        """Raise ValueError if adding a warehouse would exceed the plan limit."""
        limit = cls.WAREHOUSE_LIMITS.get(tenant.plan_tier, 0)
        if current_count >= limit:
            raise ValueError(
                f"Plan '{tenant.plan_tier}' allows max {limit} warehouses. "
                f"Current count: {current_count}. Upgrade to ENTERPRISE to add more."
            )


class StripeWebhookReceiver:
    """
    Validates Stripe webhook signatures and processes payment events.
    Updates the Client.is_active flag based on payment success/failure.
    """

    @staticmethod
    def verify_signature(payload: bytes, sig_header: str, secret: str) -> bool:
        """
        Verify Stripe webhook signature using HMAC-SHA256.
        Returns True if the signature is valid, False otherwise.
        """
        try:
            # Stripe signature format: t=<timestamp>,v1=<hash>
            elements = dict(e.split("=", 1) for e in sig_header.split(","))
            timestamp = elements.get("t", "")
            signature = elements.get("v1", "")
            signed_payload = f"{timestamp}.".encode() + payload
            expected = hmac.new(
                secret.encode(), signed_payload, hashlib.sha256
            ).hexdigest()
            return hmac.compare_digest(expected, signature)
        except Exception as e:
            logger.error("Stripe signature verification failed: %s", e)
            return False

    @staticmethod
    def handle_payment_succeeded(tenant_schema: str) -> None:
        """Re-activate tenant after successful payment."""
        try:
            client = Client.objects.get(schema_name=tenant_schema)
            client.is_active = True
            client.save(update_fields=["is_active"])
            logger.info("Tenant '%s' activated after payment success.", tenant_schema)
        except Client.DoesNotExist:
            logger.error("Stripe webhook: tenant '%s' not found.", tenant_schema)

    @staticmethod
    def handle_payment_failed(tenant_schema: str) -> None:
        """Deactivate tenant after payment failure."""
        try:
            client = Client.objects.get(schema_name=tenant_schema)
            client.is_active = False
            client.save(update_fields=["is_active"])
            logger.warning(
                "Tenant '%s' deactivated due to payment failure.", tenant_schema
            )
        except Client.DoesNotExist:
            logger.error("Stripe webhook: tenant '%s' not found.", tenant_schema)
