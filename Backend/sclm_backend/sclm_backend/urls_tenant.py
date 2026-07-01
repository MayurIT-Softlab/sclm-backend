"""
SCLM Cloud — Tenant Schema URL Configuration
Routes all 9 operational module APIs.
The JWTTenantRoutingMiddleware has already switched the DB schema
to the correct tenant before any of these views execute.
"""
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from core.views import api_health_check

urlpatterns = [
     # ── Root redirect ──────────────────────────────────────────────────────────
    # GET http://127.0.0.1:8000/ → 302 → /api/v1/users/auth/login/
    path("", RedirectView.as_view(url="/api/v1/users/auth/login/", permanent=False)),

    # ── Health check ───────────────────────────────────────────────────────────
    path("health/", api_health_check, name="public-health-check"),

    # ── Django Admin ───────────────────────────────────────────────────────────
    path("admin/", admin.site.urls),

    # ── Standard SimpleJWT endpoints (for quick testing / mobile clients) ──────
    # POST /api/token/        → standard token obtain (email+password, no tenant_id)
    # POST /api/token/refresh/ → standard token refresh
    path("api/token/", TokenObtainPairView.as_view(), name="token-obtain-pair"),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="token-refresh-standard"),

    # ── Public-schema API endpoints ────────────────────────────────────────────
    # Identity Gateway: /api/v1/users/auth/login/, /me/, /auth/logout/
    path("api/v1/users/", include("apps.users.api.urls")),
    # Tenant onboarding & subscription management
    path("api/v1/subscriptions/", include("apps.subscriptions.api.urls")),


    # ── Root redirect ──────────────────────────────────────────────────────────
    # GET http://127.0.0.1:8000/ → 302 → /api/v1/ (API index)
    path("", RedirectView.as_view(url="/health/", permanent=False)),

    # ── Health check ───────────────────────────────────────────────────────────
    path("health/", api_health_check, name="tenant-health-check"),

    # ── Tenant-schema operational modules ─────────────────────────────────────
    # Module 1 — Audit Ledger   (ADMIN-only read)
    path("api/v1/audit-ledger/", include("apps.audit_ledger.api.urls")),
    # Module 2 — Inventory      (WAREHOUSE_MGR, SOURCING_MGR, ADMIN)
    path("api/v1/inventory/", include("apps.inventory.api.urls")),
    # Module 3 — Forecasting    (SOURCING_MGR, ADMIN)
    path("api/v1/forecasting/", include("apps.forecasting.api.urls")),
    # Module 4 — Procurement    (SOURCING_MGR, ADMIN)
    path("api/v1/procurement/", include("apps.procurement.api.urls")),
    # Module 5 — Warehouse      (WAREHOUSE_MGR, ADMIN)
    path("api/v1/warehouse/", include("apps.warehouse.api.urls")),
    # Module 6 — Transportation  (LOGISTICS_MGR, ADMIN)
    path("api/v1/transportation/", include("apps.transportation.api.urls")),
    # Module 7 — Logistics       (LOGISTICS_MGR, RETAIL_USER, ADMIN)
    path("api/v1/logistics/", include("apps.logistics.api.urls")),
    # Module 8 — Returns         (WAREHOUSE_MGR, RETAIL_USER, ADMIN)
    path("api/v1/returns/", include("apps.returns.api.urls")),
    # Module 9 — Finance         (ACCOUNTANT, ADMIN)
    path("api/v1/finance/", include("apps.finance.api.urls")),
]
