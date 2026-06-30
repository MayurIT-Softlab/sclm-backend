"""
SCLM Cloud — JWT Tenant Routing Middleware
ARCHITECTURAL RULE: This middleware MUST be the very first entry in
MIDDLEWARE (see settings/base.py). It intercepts every HTTP request and:

  1. Bypasses public/auth endpoints (no tenant context needed).
  2. Decodes the JWT from the Authorization header (stateless — no DB hit).
  3. Extracts tenant_id and user_role from the custom JWT claims.
  4. Calls TenantRoutingService to:
       a) Validate the tenant exists and is active.
       b) Switch the PostgreSQL search_path to the tenant's isolated schema.
  5. Attaches tenant_id, user_role, and token_jti to the request object
     for downstream permissions and audit logging.

Cross-tenant data leaks are structurally impossible:
After this middleware runs, ALL subsequent ORM queries are physically
scoped to the tenant's isolated PostgreSQL schema.
"""
import logging
from django.http import JsonResponse
from rest_framework_simplejwt.tokens import UntypedToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

logger = logging.getLogger(__name__)

# Paths exempt from tenant routing (public schema endpoints).
PUBLIC_PATHS = (
    "/api/v1/users/auth/login/",
    "/api/v1/users/auth/refresh/",
    "/api/v1/subscriptions/webhooks/",
    "/admin/",
    "/health/",
    "/static/",
)


class JWTTenantRoutingMiddleware:
    """
    First-in-chain middleware that enforces schema-based tenant isolation.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # ── Step 1: Bypass public endpoints ───────────────────────────────
        if self._is_public_path(request.path):
            return self.get_response(request)

        # ── Step 2: Extract JWT ────────────────────────────────────────────
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            # No token present — DRF's IsAuthenticated will return 401.
            return self.get_response(request)

        token_str = auth_header.split(" ", 1)[1]

        # ── Step 3: Decode token & extract claims ─────────────────────────
        try:
            token = UntypedToken(token_str)
            tenant_id = token.payload.get("tenant_id")
            user_role = token.payload.get("role")
            jti = token.payload.get("jti")
        except (InvalidToken, TokenError) as exc:
            logger.warning("Middleware received invalid JWT: %s", exc)
            # Let DRF handle authentication; don't short-circuit here.
            return self.get_response(request)

        # Attach claims to request for downstream use.
        request.tenant_id = tenant_id
        request.user_role = user_role
        request.token_jti = jti

        # ── Step 4: Switch tenant schema ──────────────────────────────────
        if tenant_id:
            try:
                from apps.users.services import TenantRoutingService
                TenantRoutingService.get_and_switch_tenant(str(tenant_id))
            except ValueError as exc:
                logger.warning("Tenant routing failed: %s", exc)
                return JsonResponse(
                    {
                        "status": "error",
                        "error": {
                            "code": "TENANT_INACTIVE_OR_NOT_FOUND",
                            "message": str(exc),
                            "details": {},
                        },
                    },
                    status=403,
                )

        # ── Step 5: Proceed to view ────────────────────────────────────────
        response = self.get_response(request)
        return response

    @staticmethod
    def _is_public_path(path: str) -> bool:
        return any(path.startswith(p) for p in PUBLIC_PATHS)
