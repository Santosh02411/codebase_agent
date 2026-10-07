"""
Routes for user-related lookups. Currently just one: letting a dispatcher
fetch the list of registered agents, so they can pick who to assign a new
delivery to.
"""

import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime

from app.db.session import get_db
from app.models.user import UserDB, UserRole, UserOut, AreaDetectRequest, AreaSetRequest, AreaOut
from app.models.agent_location import AgentLocationDB, AgentLocationUpdate, AgentLocationOut
from app.models.location_history import AgentLocationHistoryDB
from app.models.delivery import DeliveryRecordDB, DeliveryStatus
from app.models.push_subscription import PushSubscriptionDB, PushSubscriptionCreate
from app.models.expo_push_token import ExpoPushTokenDB, ExpoPushTokenRegister
from app.routes.deliveries import require_dispatcher
from app.routes.auth import get_current_user
from app.services.push import VAPID_PUBLIC_KEY
from app.services.websocket_manager import broadcast_sync, tracking_room
from app.services.geocoding import reverse_geocode_area
from app.services.route_analytics import check_geofence_arrival, is_first_geofence_arrival
from app.services.notifications import notify_dispatchers_of_geofence_arrival
from app.services.notification_templates import send_templated_notification

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/agents", response_model=List[UserOut])
def list_agents(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_dispatcher),
):
    """Dispatcher/admin-only: list agents in the caller's organization, for the assignment dropdown."""
    return db.query(UserDB).filter(
        UserDB.role == UserRole.agent,
        UserDB.org_id == current_user.org_id,
    ).all()


@router.put("/me/location", response_model=AgentLocationOut)
def update_my_location(
    payload: AgentLocationUpdate,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    """
    An agent's device calls this periodically (see the "Share my
    location" toggle in AgentDeliveryList.jsx, driven by the browser's
    navigator.geolocation.watchPosition) while they have any active
    delivery. Upserts a single row per agent — only the latest position
    is kept (see agent_location.py for why this isn't a history log).
    """
    if current_user.role != UserRole.agent:
        raise HTTPException(status_code=403, detail="Only agents share live location.")

    existing = db.query(AgentLocationDB).filter(AgentLocationDB.agent_id == current_user.id).first()
    now = datetime.utcnow()
    if existing:
        existing.latitude = payload.latitude
        existing.longitude = payload.longitude
        existing.updated_at = now
    else:
        existing = AgentLocationDB(
            agent_id=current_user.id,
            latitude=payload.latitude,
            longitude=payload.longitude,
            updated_at=now,
        )
        db.add(existing)
    db.commit()
    db.refresh(existing)

    # Route analytics (Phase 9): also append to the location HISTORY
    # log — the "latest position" upsert above is unaffected, this is
    # purely additive. Associated with whichever delivery is currently
    # active for this agent, if any (best-effort — if there are
    # multiple, the most recently updated one is used, since that's
    # the one the agent is most likely actively working on right now).
    try:
        active_delivery = db.query(DeliveryRecordDB).filter(
            DeliveryRecordDB.agent_id == current_user.id,
            DeliveryRecordDB.status.in_([DeliveryStatus.picked_up, DeliveryStatus.out_for_delivery]),
        ).order_by(DeliveryRecordDB.updated_at.desc()).first()
        db.add(AgentLocationHistoryDB(
            org_id=current_user.org_id, agent_id=current_user.id,
            delivery_id=active_delivery.id if active_delivery else None,
            latitude=payload.latitude, longitude=payload.longitude, recorded_at=now,
        ))
        db.commit()
    except Exception:
        pass  # best-effort — never let history logging break live location sharing

    # Push the new position to anyone watching this agent's active
    # deliveries live (the customer tracking page / LiveTrackingMap) —
    # broadcasts to every delivery currently out with this agent, since
    # one location update covers all of them at once.
    active_delivery_ids = [
        row.id for row in
        db.query(DeliveryRecordDB.id).filter(
            DeliveryRecordDB.agent_id == current_user.id,
            DeliveryRecordDB.status.in_([DeliveryStatus.picked_up, DeliveryStatus.out_for_delivery]),
        ).all()
    ]
    for delivery_id in active_delivery_ids:
        broadcast_sync(tracking_room(delivery_id), {
            "event": "location_update",
            "latitude": payload.latitude,
            "longitude": payload.longitude,
        })

    # Route analytics (Phase 9): fire a geofence "arrived" alert to
    # dispatchers the first time a ping lands within range of an active
    # delivery's destination. Deliberately checked against `active_delivery`
    # (the most-recently-updated one, same as the history log above)
    # rather than every active delivery, to avoid a burst of alerts
    # when an agent legitimately has several deliveries out at once.
    if active_delivery is not None:
        try:
            if check_geofence_arrival(active_delivery, payload.latitude, payload.longitude) and is_first_geofence_arrival(db, active_delivery.id):
                notify_dispatchers_of_geofence_arrival(db, current_user.org_id, active_delivery.order_id)
                if active_delivery.customer_id:
                    send_templated_notification(
                        db, org_id=current_user.org_id, event_type="agent_nearby", order_id=active_delivery.order_id,
                        customer_id=active_delivery.customer_id, customer_email=active_delivery.customer_email,
                        customer_phone=active_delivery.customer_phone, delivery_id=active_delivery.id,
                    )
        except Exception:
            pass  # best-effort, same tolerance as every other notification send in this project

    return existing


@router.get("/deliveries/{delivery_id}/agent-location", response_model=AgentLocationOut)
def get_delivery_agent_location(
    delivery_id: str,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    """
    Fetch the assigned agent's current live location for a specific
    delivery — scoped so only someone who's actually allowed to see this
    delivery (same org staff) can see where the agent is. Customers use
    a separate, differently-scoped route in customer_dashboard.py.
    """
    delivery = db.query(DeliveryRecordDB).filter(DeliveryRecordDB.id == delivery_id).first()
    if not delivery or delivery.org_id != current_user.org_id:
        raise HTTPException(status_code=404, detail="Delivery not found.")

    location = db.query(AgentLocationDB).filter(AgentLocationDB.agent_id == delivery.agent_id).first()
    if not location:
        raise HTTPException(status_code=404, detail="Agent hasn't shared a live location yet.")
    return location


@router.post("/me/area/detect", response_model=AreaOut)
def detect_my_area(
    payload: AreaDetectRequest,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    """
    Real reverse geocoding, not a hand-typed zone field: the frontend
    sends the agent's own device GPS coordinates (from
    navigator.geolocation), and this resolves them to an actual area
    name via services/geocoding.py. That resolved name is what
    dispatcher assignment ranking matches against a delivery's `zone`
    (see routes/deliveries.py's _rank_agents_for_delivery) — so
    "assign based on area" reflects where the agent's device actually
    is, not a string a dispatcher guessed.
    """
    if current_user.role != UserRole.agent:
        raise HTTPException(status_code=403, detail="Only agents have a coverage area.")

    area_name = reverse_geocode_area(payload.latitude, payload.longitude)
    if not area_name:
        raise HTTPException(
            status_code=502,
            detail="Couldn't determine an area name for that location. Check your connection and try again.",
        )

    current_user.area_name = area_name
    current_user.area_latitude = payload.latitude
    current_user.area_longitude = payload.longitude
    db.commit()

    return AreaOut(area_name=area_name, area_latitude=payload.latitude, area_longitude=payload.longitude)


@router.get("/me/area/suggestions", response_model=List[str])
def get_area_suggestions(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    """
    Area names already in use in this org — other agents' detected/set
    areas, plus zones dispatchers have typed onto deliveries — so
    picking an area can be "choose from what's already used here"
    instead of typing blind every time. Free text is still accepted by
    POST /me/area/set regardless; this is just a convenience list.
    """
    agent_areas = (
        db.query(UserDB.area_name)
        .filter(UserDB.org_id == current_user.org_id, UserDB.area_name.isnot(None))
        .distinct()
        .all()
    )
    delivery_zones = (
        db.query(DeliveryRecordDB.zone)
        .filter(DeliveryRecordDB.org_id == current_user.org_id, DeliveryRecordDB.zone.isnot(None))
        .distinct()
        .all()
    )
    names = {row[0].strip() for row in agent_areas if row[0] and row[0].strip()}
    names |= {row[0].strip() for row in delivery_zones if row[0] and row[0].strip()}
    return sorted(names)


@router.post("/me/area/set", response_model=AreaOut)
def set_my_area_manually(
    payload: AreaSetRequest,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    """
    Sets the agent's coverage area directly, without GPS — for when the
    reverse-geocoded name from /me/area/detect isn't the name the
    dispatcher actually uses for a zone (e.g. "HSR Layout" vs. what
    Nominatim resolved to), or the agent just wants to pick their area
    outright rather than relying on their device's current location.
    No coordinates are stored for a manually-set area (there's no real
    GPS fix behind it) — only the name, which is all zone-matching in
    _rank_agents_for_delivery actually compares against anyway.
    """
    if current_user.role != UserRole.agent:
        raise HTTPException(status_code=403, detail="Only agents have a coverage area.")

    area_name = payload.area_name.strip()
    if not area_name:
        raise HTTPException(status_code=400, detail="Area name can't be empty.")

    current_user.area_name = area_name
    current_user.area_latitude = None
    current_user.area_longitude = None
    db.commit()

    return AreaOut(area_name=area_name, area_latitude=None, area_longitude=None)


@router.delete("/me/area", response_model=AreaOut)
def clear_my_area(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    """Clears a previously-detected area, e.g. if an agent's coverage has genuinely changed and the old one no longer applies."""
    if current_user.role != UserRole.agent:
        raise HTTPException(status_code=403, detail="Only agents have a coverage area.")

    current_user.area_name = None
    current_user.area_latitude = None
    current_user.area_longitude = None
    db.commit()
    return AreaOut()


@router.get("/me/push/vapid-public-key")
def get_staff_vapid_public_key():
    """Same VAPID public key as the customer-facing one — it's public by design, safe to expose to any authenticated caller or none at all."""
    return {"public_key": VAPID_PUBLIC_KEY}


@router.post("/me/push/subscribe")
def subscribe_staff_to_push(
    payload: PushSubscriptionCreate,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    """
    Saves a browser's push subscription for a staff member (agent,
    dispatcher, or admin) — so an agent gets a real OS-level notification
    the instant they're assigned a delivery, and a dispatcher/admin gets
    one the instant a new unassigned order lands. Same mechanism as the
    customer-facing subscribe endpoint, just keyed by user_id instead of
    customer_id — see models/push_subscription.py.
    """
    existing = db.query(PushSubscriptionDB).filter(PushSubscriptionDB.endpoint == payload.endpoint).first()
    if existing:
        existing.user_id = current_user.id
        existing.customer_id = None
        existing.p256dh = payload.keys.get("p256dh", "")
        existing.auth = payload.keys.get("auth", "")
    else:
        db.add(PushSubscriptionDB(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            endpoint=payload.endpoint,
            p256dh=payload.keys.get("p256dh", ""),
            auth=payload.keys.get("auth", ""),
            created_at=datetime.utcnow(),
        ))
    db.commit()
    return {"message": "Subscribed to push notifications."}


@router.post("/me/expo-push-token")
def register_expo_push_token(
    payload: ExpoPushTokenRegister,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    """
    Mobile equivalent of subscribe_staff_to_push() above — registers
    the mobile agent app's (mobile/) Expo push token instead of a
    browser's Web Push subscription, so an agent gets a real OS-level
    notification on their phone (even with the app fully closed) the
    moment they're assigned/unassigned a delivery. Called by the
    mobile app once notification permission is granted (see
    mobile/src/services/pushNotifications.js). See
    services/expo_push.py's own module docstring for why this needs no
    third-party account or API key to actually work.
    """
    existing = db.query(ExpoPushTokenDB).filter(ExpoPushTokenDB.token == payload.token).first()
    if existing:
        existing.user_id = current_user.id
    else:
        db.add(ExpoPushTokenDB(user_id=current_user.id, token=payload.token, created_at=datetime.utcnow()))
    db.commit()
    return {"message": "Registered for push notifications."}


@router.delete("/me/expo-push-token")
def unregister_expo_push_token(
    payload: ExpoPushTokenRegister,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    """
    Called on logout (see mobile/src/context/AuthContext.js) so a
    device that's no longer signed in stops receiving push
    notifications meant for whichever agent it belonged to — the same
    hygiene reason a Web Push subscription would get cleaned up on
    logout, just there's no equivalent web-side endpoint yet since the
    web app's own logout doesn't currently do this either (a real,
    pre-existing gap on the web side, not something this endpoint
    needs to solve).
    """
    db.query(ExpoPushTokenDB).filter(
        ExpoPushTokenDB.token == payload.token,
        ExpoPushTokenDB.user_id == current_user.id,
    ).delete()
    db.commit()
    return {"message": "Unregistered from push notifications."}
