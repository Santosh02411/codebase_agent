"""
WebSocket endpoints — the push side of the three previously-polling
screens (see services/websocket_manager.py's module docstring). Every
endpoint here is receive-only from the client's point of view: the
client connects, gets pushed JSON events, and does nothing else on the
socket itself — writes still go through the normal REST endpoints,
which broadcast to these rooms as a side effect after they succeed.

Auth: a browser's native WebSocket API can't set an Authorization
header on the handshake request, so staff-authenticated sockets take
the JWT as a `?token=` query parameter instead — decoded with the same
`decode_access_token` the REST auth dependency uses, just wired in
manually since FastAPI's WebSocket routes don't go through the same
Header-based dependency. The tracking socket needs no auth at all: it's
scoped to one delivery_id (an unguessable UUID), the exact same
security model the existing public GET /track/{id} REST endpoint
already uses.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.user import UserDB, UserRole
from app.models.customer import CustomerDB
from app.models.delivery import DeliveryRecordDB
from app.services.auth import decode_access_token
from app.services.websocket_manager import manager, chat_room, dispatcher_queue_room, tracking_room

router = APIRouter(tags=["websockets"])


def _get_user_from_token(token: str, db: Session) -> UserDB | None:
    payload = decode_access_token(token)
    if not payload:
        return None
    user = db.query(UserDB).filter(UserDB.id == payload.get("sub")).first()
    if not user or not user.is_active:
        return None
    return user


def _get_customer_from_token(token: str, db: Session) -> CustomerDB | None:
    """Same decode, different table — a customer's JWT `sub` is a CustomerDB id, never a UserDB one, so trying this after _get_user_from_token comes back empty is always unambiguous."""
    payload = decode_access_token(token)
    if not payload:
        return None
    return db.query(CustomerDB).filter(CustomerDB.id == payload.get("sub")).first()


@router.websocket("/ws/deliveries/{delivery_id}/messages")
async def chat_websocket(websocket: WebSocket, delivery_id: str, token: str = Query(...)):
    """
    Phase 6: this socket now authenticates EITHER a staff member (as
    before) OR the delivery's own customer — whichever the token
    decodes to. Both land in the exact same chat_room(delivery_id), so
    a staff reply and a customer message both arrive live on both
    sides of the SAME thread (see routes/messages.py and
    routes/customer_messages.py, which both broadcast into this same
    room after a successful POST).
    """
    db = SessionLocal()
    try:
        delivery = db.query(DeliveryRecordDB).filter(DeliveryRecordDB.id == delivery_id).first()
        if not delivery:
            await websocket.close(code=4404)
            return

        user = _get_user_from_token(token, db)
        if user:
            if delivery.org_id != user.org_id:
                await websocket.close(code=4404)
                return
            if user.role == UserRole.agent and delivery.agent_id != user.id:
                await websocket.close(code=4403)
                return
        else:
            customer = _get_customer_from_token(token, db)
            if not customer or delivery.customer_id != customer.id:
                await websocket.close(code=4401)
                return
    finally:
        db.close()

    room = chat_room(delivery_id)
    await manager.connect(room, websocket)
    try:
        while True:
            # This socket is push-only from the server's side — nothing
            # meaningful is ever sent BY the client over it (messages
            # are still POSTed via REST). We still need to await
            # receive_text() to detect a client-initiated disconnect;
            # anything actually received is simply ignored.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(room, websocket)


@router.websocket("/ws/dispatcher/queue")
async def dispatcher_queue_websocket(websocket: WebSocket, token: str = Query(...)):
    db = SessionLocal()
    try:
        user = _get_user_from_token(token, db)
        if not user or user.role not in (UserRole.dispatcher, UserRole.admin):
            await websocket.close(code=4403)
            return
        org_id = user.org_id
    finally:
        db.close()

    room = dispatcher_queue_room(org_id)
    await manager.connect(room, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(room, websocket)


@router.websocket("/ws/tracking/{delivery_id}")
async def tracking_websocket(websocket: WebSocket, delivery_id: str):
    """
    No auth — same security model as the existing public tracking page:
    delivery_id is an unguessable UUID, and the socket only ever
    receives updates for that one delivery, nothing else.
    """
    room = tracking_room(delivery_id)
    await manager.connect(room, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(room, websocket)
