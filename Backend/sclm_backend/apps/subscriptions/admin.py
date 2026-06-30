"""
apps.subscriptions.admin
Registers the Tenant and Domain models in the Django Admin.
"""
from django.contrib import admin
from django_tenants.admin import TenantAdminMixin
from .models import Client, Domain


@admin.register(Client)
class ClientAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ("company_name", "schema_name", "plan_tier", "is_active", "created_at")
    list_filter = ("plan_tier", "is_active")
    search_fields = ("company_name", "schema_name")
    readonly_fields = ("id", "created_at", "schema_name")


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ("domain", "tenant", "is_primary")
