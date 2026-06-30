"""
apps.subscriptions.models
Schema: public
─────────────────────────────────────────────────────────────────────────────
Client   — The Tenant model required by django-tenants (TenantMixin subclass).
           One row = one enterprise customer with its own isolated DB schema.
Domain   — Maps HTTP domain names to Tenants (required by django-tenants).
─────────────────────────────────────────────────────────────────────────────
"""
import uuid
from django.db import models
from django_tenants.models import TenantMixin, DomainMixin


class PlanTier(models.TextChoices):
    STARTER = "STARTER", "Starter"
    PROFESSIONAL = "PROFESSIONAL", "Professional"
    ENTERPRISE = "ENTERPRISE", "Enterprise"


class Client(TenantMixin):
    """
    The primary Tenant entity.

    django-tenants requires this model to:
      - Subclass TenantMixin (provides schema_name, auto_create_schema).
      - Be registered as TENANT_MODEL in settings.

    When a new Client is saved, django-tenants automatically creates a
    dedicated PostgreSQL schema (e.g., 'tenant_indore_elec') and runs
    TENANT_APPS migrations inside it.
    """
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique tenant identifier embedded in all JWT tokens.",
    )
    company_name = models.CharField(max_length=255)
    plan_tier = models.CharField(
        max_length=20,
        choices=PlanTier.choices,
        default=PlanTier.STARTER,
    )
    is_active = models.BooleanField(
        default=True,
        help_text=(
            "Set to False by the Stripe webhook receiver when payment fails. "
            "The middleware will reject JWT tokens for inactive tenants."
        ),
    )
    subscription_expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # django-tenants: auto-create the DB schema when this record is saved.
    auto_create_schema = True

    class Meta:
        app_label = "subscriptions"
        verbose_name = "Client (Tenant)"
        verbose_name_plural = "Clients (Tenants)"

    def __str__(self) -> str:
        return f"{self.company_name} [{self.schema_name}] — {self.plan_tier}"


class Domain(DomainMixin):
    """
    Maps HTTP domains to Tenants.

    django-tenants uses this to route subdomain-based multi-tenancy.
    e.g., indore-elec.sclm-cloud.com → Client(schema_name='tenant_indore_elec')

    Required by TENANT_DOMAIN_MODEL setting.
    """
    class Meta:
        app_label = "subscriptions"
        verbose_name = "Domain"
        verbose_name_plural = "Domains"

    def __str__(self) -> str:
        return self.domain
