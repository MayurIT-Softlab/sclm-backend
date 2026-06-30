"""
apps.users.api.serializers
─────────────────────────────────────────────────────────────────────────────
CustomTokenObtainPairSerializer  — Embeds tenant_id and role into JWT payload.
CustomTokenRefreshSerializer     — Standard refresh (no custom logic needed).
UserProfileSerializer            — Read-only profile view for /users/me/.
TenantMembershipSerializer       — Serializes TenantUserMapping for /me/ response.
LogoutSerializer                 — Accepts a refresh token to blacklist.
─────────────────────────────────────────────────────────────────────────────
"""
import uuid
from django.contrib.auth import authenticate
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from apps.users.models import GlobalUser, TenantUserMapping, UserRole


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Extends the default JWT login serializer to:
    1. Accept email + password + tenant_id in the request body.
    2. Validate the user is an active member of the specified tenant.
    3. Embed tenant_id and role into the JWT payload.

    The embedded claims allow the JWTTenantRoutingMiddleware to operate
    statelessly without hitting the DB on every request.
    """
    # Override default 'username' field with 'email'.
    username_field = "email"

    # Additional required field: the tenant the user is logging into.
    tenant_id = serializers.UUIDField(
        write_only=True,
        help_text="The UUID of the tenant (Client) the user is logging into.",
    )

    def validate(self, attrs):
        email = attrs.get("email")
        password = attrs.get("password")
        tenant_id = attrs.get("tenant_id")

        # Authenticate against GlobalUser.
        user = authenticate(
            request=self.context.get("request"),
            email=email,
            password=password,
        )
        if not user:
            raise serializers.ValidationError(
                {"detail": "Invalid email or password."},
                code="authentication_failed",
            )
        if not user.is_active:
            raise serializers.ValidationError(
                {"detail": "This account has been deactivated."},
                code="account_disabled",
            )

        # Validate tenant membership and get the role.
        from apps.users.services import UserAuthService
        try:
            mapping = UserAuthService.get_tenant_membership(user, tenant_id)
        except ValueError as exc:
            raise serializers.ValidationError({"detail": str(exc)}, code="tenant_access_denied")

        # Validate tenant is active.
        from apps.subscriptions.models import Client
        try:
            from django.db import connection
            connection.set_schema_to_public()
            client = Client.objects.get(id=tenant_id)
            if not client.is_active:
                raise serializers.ValidationError(
                    {"detail": "This tenant subscription is inactive. Please renew."},
                    code="tenant_inactive",
                )
        except Client.DoesNotExist:
            raise serializers.ValidationError(
                {"detail": f"Tenant '{tenant_id}' not found."},
                code="tenant_not_found",
            )

        # Generate token pair with custom claims.
        refresh = RefreshToken.for_user(user)
        refresh["tenant_id"] = str(tenant_id)
        refresh["role"] = mapping.role
        refresh["email"] = user.email

        return {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user_id": str(user.id),
            "email": user.email,
            "tenant_id": str(tenant_id),
            "role": mapping.role,
        }

    @classmethod
    def get_token(cls, user):
        """Not used directly — we override validate() for full control."""
        return super().get_token(user)


class UserProfileSerializer(serializers.ModelSerializer):
    """
    Read-only serializer for GET /users/me/
    Returns the user's profile + their membership in the current tenant.
    """
    tenant_id = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()

    class Meta:
        model = GlobalUser
        fields = ("id", "email", "is_superadmin", "date_joined", "tenant_id", "role")
        read_only_fields = fields

    def get_tenant_id(self, obj) -> str | None:
        request = self.context.get("request")
        return str(getattr(request, "tenant_id", None)) if request else None

    def get_role(self, obj) -> str | None:
        request = self.context.get("request")
        return getattr(request, "user_role", None) if request else None


class LogoutSerializer(serializers.Serializer):
    """
    Accepts the refresh token on logout so it can be blacklisted via simplejwt.
    """
    refresh = serializers.CharField(
        help_text="The refresh token issued at login.",
    )

    def validate(self, attrs):
        self.token = attrs["refresh"]
        return attrs

    def save(self, **kwargs):
        try:
            token = RefreshToken(self.token)
            token.blacklist()
        except Exception as exc:
            raise serializers.ValidationError({"detail": str(exc)})
