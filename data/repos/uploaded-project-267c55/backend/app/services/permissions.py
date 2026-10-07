"""
Permission catalog and enforcement (Phase 4). See models/rbac.py's
module docstring for the overall design (additive, not a replacement
for the existing role checks).
"""

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import UserDB, UserRole
from app.models.rbac import CustomRoleDB, RolePermissionDB
from app.routes.auth import get_current_user

# The fixed set of permissions this project recognizes, grouped by
# resource. Adding a new permission string here is safe and additive —
# nothing enforces membership in this list at the database level (a
# RolePermissionDB row is just a string), this is the source of truth
# for what routes/rbac.py's catalog endpoint advertises to the UI.
PERMISSION_CATALOG = [
    "deliveries.view", "deliveries.create", "deliveries.assign", "deliveries.update", "deliveries.cancel", "deliveries.delete",
    "users.view", "users.manage",
    "inventory.view", "inventory.manage",
    "payments.view", "payments.manage", "payments.refund",
    "analytics.view", "analytics.export",
    "workforce.view", "workforce.manage",
    "settings.view", "settings.manage",
]

# What each BASE role (agent/dispatcher/admin) is granted by default,
# used whenever a user has no custom_role_id assigned (i.e. almost
# everyone, until an admin deliberately opts someone into a custom
# role). Admin's default is irrelevant in practice since admins always
# pass every check unconditionally (see has_permission below) — listed
# here anyway so the catalog is a complete, honest picture of default
# access rather than a partial one.
ROLE_DEFAULT_PERMISSIONS = {
    UserRole.agent: {"deliveries.view", "deliveries.update", "workforce.view"},
    UserRole.dispatcher: {
        "deliveries.view", "deliveries.create", "deliveries.assign", "deliveries.update", "deliveries.cancel",
        "inventory.view", "inventory.manage",
        "payments.view",
        "analytics.view",
        "workforce.view", "workforce.manage",
        "settings.view",
    },
    UserRole.admin: set(PERMISSION_CATALOG),  # informational only — admins bypass this check entirely
}


def has_permission(db: Session, user: UserDB, permission: str) -> bool:
    """
    True if `user` is granted `permission` right now. Admins always
    pass. Otherwise: an assigned custom role's explicit grants are
    authoritative (even if that means granting LESS than the user's
    base role would have by default — an org may want a dispatcher-role
    user restricted to a narrower custom role); with no custom role
    assigned, the base role's default set applies.
    """
    if user.role == UserRole.admin:
        return True

    if user.custom_role_id:
        grants = {
            row.permission for row in db.query(RolePermissionDB).filter(
                RolePermissionDB.custom_role_id == user.custom_role_id
            ).all()
        }
        return permission in grants

    return permission in ROLE_DEFAULT_PERMISSIONS.get(user.role, set())


def require_permission(permission: str):
    """
    FastAPI dependency factory — usage: `Depends(require_permission("inventory.manage"))`.
    Real backend enforcement (never a frontend-only check): raises 403
    if the resolved current user doesn't have this permission, using
    the exact same has_permission() logic the frontend's permission-aware
    UI calls GET /admin/rbac/my-permissions to mirror (see routes/rbac.py) —
    so the two can never drift, since the UI reads its answer from this
    same function rather than duplicating the rule.
    """
    def _dependency(db: Session = Depends(get_db), current_user: UserDB = Depends(get_current_user)) -> UserDB:
        if not has_permission(db, current_user, permission):
            raise HTTPException(status_code=403, detail=f"You don't have the '{permission}' permission.")
        return current_user
    return _dependency
