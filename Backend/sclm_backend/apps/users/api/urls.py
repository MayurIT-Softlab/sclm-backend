"""
apps.users.api.urls
Route definitions for the Identity Gateway module.

All routes are prefixed with /api/v1/users/ in urls_public.py.
"""
from django.urls import path
from .views import LoginView, SCLMTokenRefreshView, MeView, LogoutView

app_name = "users"

urlpatterns = [
    # ── Public endpoints (no tenant context required) ──────────────────────
    path("auth/login/", LoginView.as_view(), name="login"),
    path("auth/refresh/", SCLMTokenRefreshView.as_view(), name="token-refresh"),

    # ── Authenticated endpoints ────────────────────────────────────────────
    path("me/", MeView.as_view(), name="me"),
    path("auth/logout/", LogoutView.as_view(), name="logout"),
]
