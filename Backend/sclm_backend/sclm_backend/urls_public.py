"""
SCLM Cloud — Public Schema URL Configuration
Routes: /admin/, /api/v1/users/, /api/v1/subscriptions/
These endpoints live in the `public` schema and are accessible
without tenant-schema switching.
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
]
