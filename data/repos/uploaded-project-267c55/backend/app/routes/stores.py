"""
Public storefront browsing — no login required, same as browsing any
e-commerce site before signing in. Only organizations that opted in via
is_public_store show up here (see organization.py) and only their
active products are listed.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import List, Optional

from app.db.session import get_db
from app.models.organization import OrganizationDB, PublicOrganizationOut
from app.models.product import ProductDB, ProductOut
from app.routes.products import _attach_review_stats
from app.services.rate_limiter import limiter

router = APIRouter(prefix="/stores", tags=["storefront"])


@router.get("/", response_model=List[PublicOrganizationOut])
@limiter.limit("60/minute")
def list_public_stores(
    request: Request,
    search: Optional[str] = None,
    category: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    The marketplace directory - every opted-in store (see
    is_public_store), optionally narrowed by a name search and/or an
    exact category match. Both params are optional and can be combined;
    with neither, this is the same full listing as before this feature
    existed. `search` matches case-insensitively anywhere in the store's
    name; `category` is an exact, case-insensitive match against the
    admin-set category (see StoreProfileUpdate) — free text, not an
    enum, since real vendor categories aren't known in advance.
    """
    query = db.query(OrganizationDB).filter(OrganizationDB.is_public_store == True, OrganizationDB.is_suspended == False)  # noqa: E712
    if search:
        query = query.filter(OrganizationDB.name.ilike(f"%{search}%"))
    if category:
        query = query.filter(OrganizationDB.category.ilike(category))
    return query.all()


@router.get("/categories", response_model=List[str])
@limiter.limit("60/minute")
def list_store_categories(request: Request, db: Session = Depends(get_db)):
    """Distinct categories currently in use across public stores, for the marketplace's filter dropdown."""
    rows = db.query(OrganizationDB.category).filter(
        OrganizationDB.is_public_store == True,  # noqa: E712
        OrganizationDB.category.isnot(None),
        OrganizationDB.category != "",
    ).distinct().all()
    return sorted({row[0] for row in rows})


@router.get("/{org_id}/products", response_model=List[ProductOut])
@limiter.limit("60/minute")
def list_store_products(request: Request, org_id: str, db: Session = Depends(get_db)):
    store = db.query(OrganizationDB).filter(
        OrganizationDB.id == org_id,
        OrganizationDB.is_public_store == True,  # noqa: E712
    ).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found.")

    products = db.query(ProductDB).filter(
        ProductDB.org_id == org_id,
        ProductDB.is_active == True,  # noqa: E712
    ).all()
    return _attach_review_stats(db, products)
