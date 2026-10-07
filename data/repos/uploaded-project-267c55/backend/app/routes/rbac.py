"""
Granular RBAC routes (Phase 4): the permission catalog (for building
permission-aware UI), custom role CRUD, and assigning a custom role to
a user. All admin-only — creating/editing what OTHER users can do is
an admin action in this project the same way user activation/
deactivation already is (routes/admin.py).
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.db.session import get_db
from app.models.user import UserDB
from app.models.rbac import (
    CustomRoleDB, RolePermissionDB,
    CustomRoleCreate, CustomRoleUpdate, CustomRoleOut, RoleAssignmentIn,
)
from app.routes.admin import require_admin
from app.routes.auth import get_current_user
from app.services.permissions import PERMISSION_CATALOG, has_permission
from app.services.action_log import record_action

router = APIRouter(prefix="/admin/rbac", tags=["rbac"])


def _role_out(db: Session, role: CustomRoleDB) -> CustomRoleOut:
    perms = [r.permission for r in db.query(RolePermissionDB).filter(RolePermissionDB.custom_role_id == role.id).all()]
    return CustomRoleOut(
        id=role.id, org_id=role.org_id, name=role.name, description=role.description,
        created_at=role.created_at, permissions=sorted(perms),
    )


@router.get("/permissions-catalog")
def get_permissions_catalog(current_user: UserDB = Depends(require_admin)):
    """The full fixed list of permissions this project recognizes, for building a permission picker in the custom-role editor."""
    return {"permissions": PERMISSION_CATALOG}


@router.get("/my-permissions")
def get_my_permissions(db: Session = Depends(get_db), current_user: UserDB = Depends(get_current_user)):
    """
    Every logged-in user (any role) can check their OWN resolved
    permission set — this is what a permission-aware frontend nav/button
    should call rather than re-implementing the admin/custom-role/
    default-role resolution logic itself.
    """
    return {"permissions": sorted(p for p in PERMISSION_CATALOG if has_permission(db, current_user, p))}


@router.get("/roles", response_model=List[CustomRoleOut])
def list_custom_roles(db: Session = Depends(get_db), current_user: UserDB = Depends(require_admin)):
    roles = db.query(CustomRoleDB).filter(CustomRoleDB.org_id == current_user.org_id).order_by(CustomRoleDB.created_at.asc()).all()
    return [_role_out(db, r) for r in roles]


@router.post("/roles", response_model=CustomRoleOut)
def create_custom_role(payload: CustomRoleCreate, db: Session = Depends(get_db), current_user: UserDB = Depends(require_admin)):
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Name can't be empty.")
    unknown = set(payload.permissions) - set(PERMISSION_CATALOG)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown permission(s): {', '.join(sorted(unknown))}")

    role = CustomRoleDB(org_id=current_user.org_id, name=payload.name.strip(), description=payload.description)
    db.add(role)
    db.commit()
    db.refresh(role)
    for perm in set(payload.permissions):
        db.add(RolePermissionDB(custom_role_id=role.id, permission=perm))
    db.commit()

    record_action(
        db, org_id=current_user.org_id, actor_user_id=current_user.id,
        actor_display_name=current_user.display_name, action="create",
        entity_type="custom_role", entity_id=role.id, entity_label=role.name,
        summary=f"Created custom role '{role.name}' with {len(payload.permissions)} permission(s).",
    )
    return _role_out(db, role)


@router.patch("/roles/{role_id}", response_model=CustomRoleOut)
def update_custom_role(role_id: str, payload: CustomRoleUpdate, db: Session = Depends(get_db), current_user: UserDB = Depends(require_admin)):
    role = db.query(CustomRoleDB).filter(CustomRoleDB.id == role_id, CustomRoleDB.org_id == current_user.org_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Custom role not found.")

    before_perms = sorted(r.permission for r in db.query(RolePermissionDB).filter(RolePermissionDB.custom_role_id == role.id).all())

    if payload.name is not None:
        role.name = payload.name.strip()
    if payload.description is not None:
        role.description = payload.description
    if payload.permissions is not None:
        unknown = set(payload.permissions) - set(PERMISSION_CATALOG)
        if unknown:
            raise HTTPException(status_code=400, detail=f"Unknown permission(s): {', '.join(sorted(unknown))}")
        db.query(RolePermissionDB).filter(RolePermissionDB.custom_role_id == role.id).delete()
        for perm in set(payload.permissions):
            db.add(RolePermissionDB(custom_role_id=role.id, permission=perm))
    db.commit()
    db.refresh(role)

    record_action(
        db, org_id=current_user.org_id, actor_user_id=current_user.id,
        actor_display_name=current_user.display_name, action="update",
        entity_type="custom_role", entity_id=role.id, entity_label=role.name,
        summary=f"Updated custom role '{role.name}'.",
        before={"permissions": before_perms}, after={"permissions": sorted(payload.permissions or before_perms)},
    )
    return _role_out(db, role)


@router.delete("/roles/{role_id}")
def delete_custom_role(role_id: str, db: Session = Depends(get_db), current_user: UserDB = Depends(require_admin)):
    role = db.query(CustomRoleDB).filter(CustomRoleDB.id == role_id, CustomRoleDB.org_id == current_user.org_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Custom role not found.")

    # Anyone currently assigned this role falls back to their base
    # role's default permissions — never left pointing at a deleted row.
    reassigned = db.query(UserDB).filter(UserDB.custom_role_id == role_id, UserDB.org_id == current_user.org_id).all()
    for u in reassigned:
        u.custom_role_id = None

    db.query(RolePermissionDB).filter(RolePermissionDB.custom_role_id == role_id).delete()
    db.delete(role)
    db.commit()
    return {"message": "Custom role deleted.", "users_reset_to_default": len(reassigned)}


@router.post("/users/{user_id}/role", response_model=dict)
def assign_custom_role(user_id: str, payload: RoleAssignmentIn, db: Session = Depends(get_db), current_user: UserDB = Depends(require_admin)):
    target = db.query(UserDB).filter(UserDB.id == user_id, UserDB.org_id == current_user.org_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found.")

    if payload.custom_role_id:
        role = db.query(CustomRoleDB).filter(CustomRoleDB.id == payload.custom_role_id, CustomRoleDB.org_id == current_user.org_id).first()
        if not role:
            raise HTTPException(status_code=404, detail="Custom role not found.")

    before = target.custom_role_id
    target.custom_role_id = payload.custom_role_id
    db.commit()

    record_action(
        db, org_id=current_user.org_id, actor_user_id=current_user.id,
        actor_display_name=current_user.display_name, action="update",
        entity_type="user_role_assignment", entity_id=target.id, entity_label=target.display_name,
        summary=f"Changed {target.display_name}'s custom role assignment.",
        before={"custom_role_id": before}, after={"custom_role_id": payload.custom_role_id},
    )
    return {"message": "Role assignment updated.", "user_id": target.id, "custom_role_id": target.custom_role_id}
