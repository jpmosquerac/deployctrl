from __future__ import annotations

from datetime import datetime, timezone

import bcrypt
from mongoengine import (
    BooleanField,
    DateTimeField,
    Document,
    EmailField,
    ListField,
    StringField,
)

# ---------------------------------------------------------------------------
# RBAC: built-in role → permissions mapping
# ---------------------------------------------------------------------------
PERMISSIONS = {
    # Catalog
    'view_catalog': 'Browse infrastructure templates',
    # Requests
    'create_request': 'Submit a new infrastructure request',
    'view_own_requests': 'View own infrastructure requests',
    'view_requests_all': 'View all infrastructure requests',
    'approve_request': 'Approve a pending request',
    'reject_request': 'Reject a pending request',
    'provision_request': 'Mark a request as provisioned',
    'decommission_request': 'Decommission a provisioned deployment',
    'manage_templates': 'Create, edit, and delete infrastructure templates',
    # Governance
    'view_audit': 'View the immutable audit log',
    'view_deployments': 'View Terraform deployment runs and logs',
    'manage_gitops': 'Configure GitOps integration',
    # Users
    'view_users': 'List all platform users',
    'manage_users': 'Create, update, and deactivate users',
}

ROLE_PERMISSIONS: dict[str, list[str]] = {
    'admin': ['*'],  # wildcard = all permissions
    'architect': [
        'view_catalog',
        'create_request',
        'view_own_requests',
        'view_requests_all',
        'approve_request',
        'reject_request',
        'provision_request',
        'decommission_request',
        'manage_templates',
        'view_audit',
        'view_deployments',
        'manage_gitops',
        'view_users',
    ],
    'developer': [
        'view_catalog',
        'create_request',
        'view_own_requests',
    ],
    'user': [
        'view_catalog',
        'view_own_requests',
    ],
}

ROLE_CHOICES = ('developer', 'architect', 'admin', 'user')


# ---------------------------------------------------------------------------
# MongoDB Documents
# ---------------------------------------------------------------------------

class Permission(Document):
    """Registry of all available permissions."""
    codename = StringField(max_length=60, unique=True, required=True)
    description = StringField(default='')

    meta = {
        'collection': 'permissions',
        'indexes': ['codename'],
    }

    def __str__(self):
        return self.codename


class Role(Document):
    """A named role with an explicit list of granted permissions."""
    name = StringField(max_length=30, unique=True, required=True)
    description = StringField(default='')
    permissions = ListField(StringField(max_length=60))

    meta = {
        'collection': 'roles',
        'indexes': ['name'],
    }

    def __str__(self):
        return self.name

    def has_permission(self, perm: str) -> bool:
        return '*' in self.permissions or perm in self.permissions


class MongoUser(Document):
    """Primary user document stored in MongoDB."""
    username = StringField(max_length=150, unique=True, required=True)
    email = EmailField(unique=True, required=True)
    password_hash = StringField(required=True)
    first_name = StringField(max_length=100, default='')
    last_name = StringField(max_length=100, default='')
    role = StringField(choices=ROLE_CHOICES, default='developer')
    team = StringField(max_length=100, default='')
    is_active = BooleanField(default=True)
    created_at = DateTimeField(default=lambda: datetime.now(timezone.utc))
    last_login = DateTimeField(null=True)

    meta = {
        'collection': 'users',
        'indexes': ['username', 'email'],
    }

    # ── Password helpers ──────────────────────────────────────────────────

    def set_password(self, raw: str) -> None:
        self.password_hash = bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode()

    def check_password(self, raw: str) -> bool:
        return bcrypt.checkpw(raw.encode(), self.password_hash.encode())

    # ── RBAC ─────────────────────────────────────────────────────────────

    def _role_perms(self) -> list[str]:
        """Return the effective permission list for this user's role.

        Checks the MongoDB-stored Role document first so that RBAC changes
        made via the UI persist across server restarts. Falls back to the
        hardcoded defaults when no MongoDB document exists for the role.
        """
        db_role = Role.objects(name=self.role).first()
        if db_role is not None:
            return db_role.permissions
        return ROLE_PERMISSIONS.get(self.role, [])

    def has_permission(self, perm: str) -> bool:
        role_perms = self._role_perms()
        return '*' in role_perms or perm in role_perms

    def get_permissions(self) -> list[str]:
        role_perms = self._role_perms()
        if '*' in role_perms:
            return list(PERMISSIONS.keys())
        return role_perms

    # ── Django / DRF compatibility ────────────────────────────────────────

    @property
    def is_authenticated(self) -> bool:
        return bool(self.is_active)

    @property
    def is_anonymous(self) -> bool:
        return False

    @property
    def id_str(self) -> str:
        return str(self.id)

    def get_full_name(self) -> str:
        return f'{self.first_name} {self.last_name}'.strip() or self.username

    def __str__(self):
        return f'{self.get_full_name()} <{self.email}> [{self.role}]'
