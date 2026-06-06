"""
RBAC permission classes for Django REST Framework.

Usage in views:
    from apps.accounts.rbac import require_permission, IsArchitectOrAdmin

    class MyView(APIView):
        permission_classes = [require_permission('approve_request')]
"""
from typing import Optional
from rest_framework.permissions import BasePermission


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class IsMongoAuthenticated(BasePermission):
    """Require a valid MongoDB-backed JWT session."""

    def has_permission(self, request, view):
        return bool(request.user and getattr(request.user, 'is_authenticated', False))


class HasPermission(BasePermission):
    """Check a specific RBAC permission on the MongoUser."""
    required_permission: Optional[str] = None

    def has_permission(self, request, view):
        if not request.user or not getattr(request.user, 'is_authenticated', False):
            return False
        if self.required_permission is None:
            return True
        return request.user.has_permission(self.required_permission)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def require_permission(perm: str) -> type[HasPermission]:
    """
    Dynamically create a DRF permission class for `perm`.

    Example:
        permission_classes = [require_permission('manage_policy')]
    """
    cls = type(
        f'Requires_{perm}',
        (HasPermission,),
        {'required_permission': perm},
    )
    return cls


# ---------------------------------------------------------------------------
# Convenience classes (most commonly used)
# ---------------------------------------------------------------------------

CanViewCatalog       = require_permission('view_catalog')
CanCreateRequest     = require_permission('create_request')
CanViewOwnRequests   = require_permission('view_own_requests')
CanViewAllRequests   = require_permission('view_requests_all')
CanApproveRequest    = require_permission('approve_request')
CanRejectRequest     = require_permission('reject_request')
CanProvisionRequest  = require_permission('provision_request')
CanViewAudit         = require_permission('view_audit')
CanViewDeployments   = require_permission('view_deployments')
CanManageGitOps      = require_permission('manage_gitops')
CanViewUsers         = require_permission('view_users')
CanManageUsers       = require_permission('manage_users')


class IsArchitectOrAdmin(BasePermission):
    """Shorthand: role must be architect or admin."""

    def has_permission(self, request, view):
        if not request.user or not getattr(request.user, 'is_authenticated', False):
            return False
        return request.user.role in ('architect', 'admin')


class IsAdmin(BasePermission):
    """Role must be admin."""

    def has_permission(self, request, view):
        if not request.user or not getattr(request.user, 'is_authenticated', False):
            return False
        return request.user.role == 'admin'
