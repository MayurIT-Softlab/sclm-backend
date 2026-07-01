"""
apps.users.services
TenantRoutingService — Resolves tenant from JWT claims, validates active status.
RBACEnforcerService  — Role-to-endpoint permission matrix.
UserAuthService      — Login, logout, token blacklisting.
"""
import logging
import uuid
from django.db import connection
from django.core.cache import cache

logger = logging.getLogger(__name__)

# Cache TTL for tenant lookups — avoids hitting the DB on every request.
TENANT_CACHE_TTL = 300  # 5 minutes


class TenantRoutingService:
    """
    Resolves a tenant from its UUID, validates it is active,
    and switches the PostgreSQL search_path.

    This service is called by the JWTTenantRoutingMiddleware on every
    authenticated request. It uses Redis caching to avoid a DB lookup
    on every request.
    """

    @classmethod
    def get_and_switch_tenant(cls, tenant_id_str: str) -> "apps.subscriptions.models.Client":  # type: ignore[name-defined]
        """
        1. Validate tenant_id is a valid UUID.
        2. Look up the Client in the public schema (with Redis cache).
        3. Assert the tenant is active.
        4. Switch the DB connection to the tenant's schema.

        Raises:
            ValueError: If tenant not found or inactive.
        """
        # Import here to avoid circular imports at module load time.
        from apps.subscriptions.models import Client

        # Validate UUID format.
        try:
            tenant_uuid = uuid.UUID(tenant_id_str)
        except (ValueError, AttributeError):
            raise ValueError(f"Invalid tenant_id format: {tenant_id_str!r}")

        # Check Redis cache first.
        cache_key = f"tenant_schema:{tenant_uuid}"
        cached = cache.get(cache_key)
        if cached:
            schema_name, is_active = cached
        else:
            try:
                # Ensure we query the public schema for Client.
                connection.set_schema_to_public()
                client = Client.objects.get(id=tenant_uuid)
                schema_name = client.schema_name
                is_active = client.is_active
                # Cache the schema_name + is_active tuple.
                cache.set(cache_key, (schema_name, is_active), TENANT_CACHE_TTL)
            except Client.DoesNotExist:
                raise ValueError(f"Tenant with id '{tenant_uuid}' does not exist.")

        if not is_active:
            raise ValueError(
                f"Tenant '{tenant_uuid}' subscription is inactive. "
                "Access denied."
            )

        # Switch the PostgreSQL search_path for this DB connection.
        connection.set_schema(schema_name)
        logger.debug("Switched schema to '%s' for tenant '%s'.", schema_name, tenant_uuid)

        return schema_name

    @classmethod
    def invalidate_cache(cls, tenant_id: uuid.UUID) -> None:
        """Call this when a tenant's is_active or schema_name changes."""
        cache.delete(f"tenant_schema:{tenant_id}")


class RBACEnforcerService:
    """
    Validates that a user's role grants access to the requested endpoint.
    Used by the custom DRF permission classes (see permissions.py).

    Permission Matrix (from Backend Schema Doc):
      ADMIN           → Full access to all modules inside their schema
                        + exclusive GET on audit_ledger
      WAREHOUSE_MGR   → GET/POST on warehouse, inventory
      SOURCING_MGR    → GET/POST on procurement, forecasting
      LOGISTICS_MGR   → GET/POST on transportation, logistics
      ACCOUNTANT      → GET/POST on finance
      RETAIL_USER     → GET/POST on logistics (sales orders), returns
    """
    from apps.users.models import UserRole  # local import to avoid circulars

    # Maps URL path prefixes to the minimum roles allowed.
    ROUTE_PERMISSIONS: dict[str, list[str]] = {
        "/api/v1/audit-ledger/": ["ADMIN"],
        "/api/v1/inventory/": ["ADMIN", "WAREHOUSE_MGR", "SOURCING_MGR"],
        "/api/v1/forecasting/": ["ADMIN", "SOURCING_MGR"],
        "/api/v1/procurement/": ["ADMIN", "SOURCING_MGR"],
        "/api/v1/warehouse/": ["ADMIN", "WAREHOUSE_MGR"],
        "/api/v1/transportation/": ["ADMIN", "LOGISTICS_MGR"],
        "/api/v1/logistics/": ["ADMIN", "LOGISTICS_MGR", "RETAIL_USER"],
        "/api/v1/returns/": ["ADMIN", "WAREHOUSE_MGR", "RETAIL_USER"],
        "/api/v1/finance/": ["ADMIN", "ACCOUNTANT"],
    }

    @classmethod
    def is_allowed(cls, role: str, path: str) -> bool:
        """Return True if the given role can access the given URL path."""
        for prefix, allowed_roles in cls.ROUTE_PERMISSIONS.items():
            if path.startswith(prefix):
                return role in allowed_roles
        # Unknown path — default deny for safety.
        return False


class UserAuthService:
    """
    Handles login-adjacent business logic:
    - Validates user credentials and tenant membership.
    - Blacklists tokens on logout.
    """

    @classmethod
    def get_tenant_membership(cls, user, tenant_id: uuid.UUID):
        """
        Returns the TenantUserMapping for the given user+tenant pair.
        Raises ValueError if the mapping doesn't exist or is inactive.
        """
        from apps.users.models import TenantUserMapping

        try:
            mapping = TenantUserMapping.objects.select_related("user").get(
                user=user,
                tenant_id=tenant_id,
                is_active=True,
            )
            return mapping
        except TenantUserMapping.DoesNotExist:
            raise ValueError(
                f"User '{user.email}' is not an active member of tenant '{tenant_id}'."
            )

    @classmethod
    def blacklist_token(cls, user, jti: str) -> None:
        """Record an access token's JTI as blacklisted (logout flow)."""
        from apps.users.models import JwtBlacklistedToken

        JwtBlacklistedToken.objects.get_or_create(jti=jti, defaults={"user": user})
        logger.info("Token JTI '%s...' blacklisted for user '%s'.", jti[:8], user.email)

    @classmethod
    def is_token_blacklisted(cls, jti: str) -> bool:
        """Return True if the given JTI has been blacklisted."""
        from apps.users.models import JwtBlacklistedToken

        return JwtBlacklistedToken.objects.filter(jti=jti).exists()
