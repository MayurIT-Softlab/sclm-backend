"""
apps.users.models
Schema: public
─────────────────────────────────────────────────────────────────────────────
GlobalUser        — The single authentication identity for all tenants.
                    Does NOT subclass AbstractUser to avoid Django's
                    auth permission tables polluting the public schema.
                    Uses email as the login credential.

TenantUserMapping — The RBAC gate. Maps one GlobalUser to one Client
                    (tenant) with a strict role enum. A user can be
                    a WAREHOUSE_MGR in Company A and an ACCOUNTANT in
                    Company B — they are different mapping rows.

JwtBlacklistedToken — Tracks revoked/logged-out JWT tokens by their
                      JTI (JWT ID) claim for stateless session invalidation.
─────────────────────────────────────────────────────────────────────────────
"""
import uuid
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models


# ─────────────────────────────────────────────────────────────────────────────
# Role Enum
# ─────────────────────────────────────────────────────────────────────────────

class UserRole(models.TextChoices):
    ADMIN = "ADMIN", "Enterprise Admin"
    WAREHOUSE_MGR = "WAREHOUSE_MGR", "Warehouse Manager"
    SOURCING_MGR = "SOURCING_MGR", "Sourcing Manager"
    LOGISTICS_MGR = "LOGISTICS_MGR", "Logistics Manager"
    ACCOUNTANT = "ACCOUNTANT", "Accountant"
    RETAIL_USER = "RETAIL_USER", "Retail User"


# ─────────────────────────────────────────────────────────────────────────────
# GlobalUser Manager
# ─────────────────────────────────────────────────────────────────────────────

class GlobalUserManager(BaseUserManager):
    """Custom manager for email-based authentication."""

    def create_user(self, email: str, password: str, **extra_fields):
        if not email:
            raise ValueError("Email is required.")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str, **extra_fields):
        extra_fields.setdefault("is_superadmin", True)
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra_fields)


# ─────────────────────────────────────────────────────────────────────────────
# GlobalUser
# ─────────────────────────────────────────────────────────────────────────────

class GlobalUser(AbstractBaseUser, PermissionsMixin):
    """
    The single, canonical user identity across all tenants.

    A GlobalUser does NOT belong to a tenant — that link is established
    through TenantUserMapping. This allows one human to be a member of
    multiple enterprise tenants (with different roles in each).

    Uses email as the primary login credential (USERNAME_FIELD).
    """
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    email = models.EmailField(
        unique=True,
        db_index=True,
        help_text="Primary login credential. Must be unique across all tenants.",
    )
    is_superadmin = models.BooleanField(
        default=False,
        help_text="SaaS Super Admin — has global platform management access.",
    )
    # Required by Django Admin and PermissionsMixin
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    last_login = models.DateTimeField(null=True, blank=True)
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = GlobalUserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        app_label = "users"
        verbose_name = "Global User"
        verbose_name_plural = "Global Users"
        indexes = [
            models.Index(fields=["email"], name="users_globaluser_email_idx"),
        ]

    def __str__(self) -> str:
        tag = " [SuperAdmin]" if self.is_superadmin else ""
        return f"{self.email}{tag}"

    def get_full_name(self) -> str:
        return self.email

    def get_short_name(self) -> str:
        return self.email.split("@")[0]


# ─────────────────────────────────────────────────────────────────────────────
# TenantUserMapping (RBAC Gate)
# ─────────────────────────────────────────────────────────────────────────────

class TenantUserMapping(models.Model):
    """
    Maps a GlobalUser to a specific Client (tenant) with a role.

    This is the RBAC control plane. When the JWT middleware decodes the
    token, it reads:
      - token["tenant_id"] → finds the Client
      - token["role"]      → validates the user's permission level

    The composite unique index (user_id, tenant_id) ensures a user
    can only have one role per tenant, but can be in multiple tenants.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        GlobalUser,
        on_delete=models.CASCADE,
        related_name="tenant_memberships",
        db_index=True,
    )
    # Intentionally a UUID field (not FK) to avoid cross-schema FK constraints.
    # The tenant lives in the public schema; the FK would normally work, but
    # storing it as a UUID + validating in the service layer is safer.
    tenant_id = models.UUIDField(
        db_index=True,
        help_text="UUID of the Client (Tenant). Validated by the service layer.",
    )
    role = models.CharField(
        max_length=20,
        choices=UserRole.choices,
        default=UserRole.RETAIL_USER,
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Soft-disable a user's access to a specific tenant.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "users"
        verbose_name = "Tenant User Mapping"
        verbose_name_plural = "Tenant User Mappings"
        # A user can only have ONE role per tenant.
        unique_together = [("user", "tenant_id")]
        indexes = [
            models.Index(fields=["user", "tenant_id"], name="users_mapping_user_tenant_idx"),
            models.Index(fields=["tenant_id"], name="users_mapping_tenant_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user.email} → tenant:{self.tenant_id} [{self.role}]"


# ─────────────────────────────────────────────────────────────────────────────
# JwtBlacklistedToken (Session Revocation)
# ─────────────────────────────────────────────────────────────────────────────

class JwtBlacklistedToken(models.Model):
    """
    Tracks revoked JWT tokens by their JTI (JWT ID) claim.

    Because we use stateless JWTs, we cannot "delete" an issued token.
    Instead, on logout or forced-revocation, we store the JTI here.
    The JWTAuthentication backend checks this table before accepting a token.

    Note: simplejwt's built-in token_blacklist app handles refresh token
    rotation. This model covers ACCESS token revocation (e.g., forced logout).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    jti = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="The 'jti' claim from the JWT payload.",
    )
    user = models.ForeignKey(
        GlobalUser,
        on_delete=models.CASCADE,
        related_name="blacklisted_tokens",
    )
    blacklisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "users"
        verbose_name = "Blacklisted JWT Token"
        verbose_name_plural = "Blacklisted JWT Tokens"
        indexes = [
            models.Index(fields=["jti"], name="users_blacklist_jti_idx"),
        ]

    def __str__(self) -> str:
        return f"Blacklisted JTI:{self.jti[:12]}... ({self.user.email})"
