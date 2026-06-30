"""
apps.users.admin
Admin registration for GlobalUser, TenantUserMapping, JwtBlacklistedToken.
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import GlobalUser, TenantUserMapping, JwtBlacklistedToken


@admin.register(GlobalUser)
class GlobalUserAdmin(UserAdmin):
    model = GlobalUser
    list_display = ("email", "is_superadmin", "is_active", "is_staff", "date_joined")
    list_filter = ("is_superadmin", "is_active", "is_staff")
    search_fields = ("email",)
    ordering = ("-date_joined",)
    readonly_fields = ("id", "date_joined", "last_login")

    # Customize fieldsets since we don't have first_name/last_name.
    fieldsets = (
        (None, {"fields": ("id", "email", "password")}),
        ("Flags", {"fields": ("is_active", "is_staff", "is_superuser", "is_superadmin")}),
        ("Timestamps", {"fields": ("date_joined", "last_login")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "password1", "password2", "is_superadmin"),
        }),
    )


@admin.register(TenantUserMapping)
class TenantUserMappingAdmin(admin.ModelAdmin):
    list_display = ("user", "tenant_id", "role", "is_active", "created_at")
    list_filter = ("role", "is_active")
    search_fields = ("user__email",)
    readonly_fields = ("id", "created_at")


@admin.register(JwtBlacklistedToken)
class JwtBlacklistedTokenAdmin(admin.ModelAdmin):
    list_display = ("jti", "user", "blacklisted_at")
    search_fields = ("jti", "user__email")
    readonly_fields = ("id", "blacklisted_at")
