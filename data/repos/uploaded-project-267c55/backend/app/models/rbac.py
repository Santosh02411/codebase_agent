"""
Granular RBAC (Phase 4) — layered ADDITIVELY on top of the existing
three-value UserDB.role (agent/dispatcher/admin), not a replacement
for it.

Why additive: UserDB.role and the require_admin()/require_dispatcher()
dependencies it powers are checked directly in essentially every
existing route across this project (30+ files). Migrating every one of
those checks to a permission lookup in this pass would touch a huge,
high-risk surface for a single phase. Instead:

  - The fixed PERMISSION_CATALOG below enumerates every permission this
    project recognizes (see services/permissions.py for the full list
    and the base-role default grants).
  - CustomRoleDB lets an org define its own named roles, each granted an
    explicit SET of permissions (RolePermissionDB, one row per grant).
  - UserDB gains one new nullable `custom_role_id` column. It changes
    NOTHING about how a user's base UserRole (agent/dispatcher/admin)
    already works — every existing require_admin()/require_dispatcher()
    check in the app is completely unaffected and unmodified.
  - A NEW dependency, require_permission(perm) (see routes/rbac.py),
    checks: an admin always passes; otherwise the user's assigned custom
    role must explicitly grant that permission, else the base role's
    DEFAULT grants apply (see PERMISSION_CATALOG's role_defaults). This
    is real, enforced, backend authorization — never a frontend-only
    check — and it's what protects every Phase 3 warehouse/supplier/PO
    endpoint (routes/warehouse.py), demonstrating it end-to-end on real
    functionality rather than as an unused, decorative system.

Retrofitting every pre-existing endpoint in the app onto
require_permission() is explicitly OUT of scope for this phase (see the
completion report) — that's a large, separate migration best done
incrementally, route family by route family, with its own regression
testing, not bundled into this pass.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, ForeignKey
from pydantic import BaseModel
from typing import Optional, List

from app.db.session import Base


class CustomRoleDB(Base):
    __tablename__ = "custom_roles"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, index=True, nullable=False)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class RolePermissionDB(Base):
    __tablename__ = "role_permissions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    custom_role_id = Column(String, index=True, nullable=False)
    permission = Column(String, nullable=False)  # one of PERMISSION_CATALOG's keys


# ---------- Pydantic Schemas ----------

class CustomRoleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    permissions: List[str] = []


class CustomRoleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    permissions: Optional[List[str]] = None


class CustomRoleOut(BaseModel):
    id: str
    org_id: str
    name: str
    description: Optional[str] = None
    created_at: datetime
    permissions: List[str] = []

    class Config:
        from_attributes = True


class RoleAssignmentIn(BaseModel):
    custom_role_id: Optional[str] = None  # None clears the assignment, falling back to base-role defaults
