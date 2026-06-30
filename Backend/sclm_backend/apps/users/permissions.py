"""
apps.users.permissions
Custom DRF Permission Classes backed by RBACEnforcerService.
Applied at the ViewSet level across all 11 modules.
"""
from rest_framework.permissions import BasePermission
from .services import RBACEnforcerService, UserAuthService
import logging

logger = logging.getLogger(__name__)


class IsActiveTenant(BasePermission):
    """
    Grants access only if the request has a valid, active tenant context.
    This is the baseline permission applied to all tenant-schema endpoints.
    """
    message = "Your tenant subscription is inactive or invalid."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and getattr(request, "tenant_id", None) is not None
        )


class RBACPermission(BasePermission):
    """
    Role-Based Access Control permission class.
    Checks the user's role (embedded in the JWT) against the
    RBACEnforcerService.ROUTE_PERMISSIONS matrix.

    Usage in a ViewSet:
        permission_classes = [IsAuthenticated, RBACPermission]
    """
    message = "You do not have permission to access this module."

    def has_permission(self, request, view):
        role = getattr(request, "user_role", None)
        if not role:
            logger.warning(
                "RBACPermission: no role on request for path '%s'.",
                request.path,
            )
            return False

        allowed = RBACEnforcerService.is_allowed(role, request.path)
        if not allowed:
            logger.warning(
                "RBAC denied: role='%s' path='%s'", role, request.path
            )
        return allowed


class IsAdminRole(BasePermission):
    """Allows access only to ADMIN role (Enterprise Admin)."""
    message = "Only Enterprise Admins can perform this action."

    def has_permission(self, request, view):
        return getattr(request, "user_role", None) == "ADMIN"


class IsWarehouseManager(BasePermission):
    """Allows ADMIN or WAREHOUSE_MGR."""
    message = "Warehouse Manager or Admin role required."

    def has_permission(self, request, view):
        return getattr(request, "user_role", None) in ("ADMIN", "WAREHOUSE_MGR")


class IsSourcingManager(BasePermission):
    """Allows ADMIN or SOURCING_MGR."""
    message = "Sourcing Manager or Admin role required."

    def has_permission(self, request, view):
        return getattr(request, "user_role", None) in ("ADMIN", "SOURCING_MGR")


class IsLogisticsManager(BasePermission):
    """Allows ADMIN or LOGISTICS_MGR."""
    message = "Logistics Manager or Admin role required."

    def has_permission(self, request, view):
        return getattr(request, "user_role", None) in ("ADMIN", "LOGISTICS_MGR")


class IsAccountant(BasePermission):
    """Allows ADMIN or ACCOUNTANT."""
    message = "Accountant or Admin role required."

    def has_permission(self, request, view):
        return getattr(request, "user_role", None) in ("ADMIN", "ACCOUNTANT")


class HasValidJTI(BasePermission):
    """
    Validates that the JWT's JTI claim has not been blacklisted.
    Applied to sensitive write endpoints.
    """
    message = "This session has been revoked. Please log in again."

    def has_permission(self, request, view):
        jti = getattr(request, "token_jti", None)
        if not jti:
            return True  # No JTI extracted — let JWT auth handle it
        return not UserAuthService.is_token_blacklisted(jti)
