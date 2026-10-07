"""
Sends a customer notification when a delivery's status changes, via
whichever contact channel(s) are actually on file for that delivery.
Neither, either, or both of email/SMS may fire — nothing is required.

Kept as its own thin module (rather than calling email.py/sms.py
directly from the route/conflict-resolver code) so the call site only
needs to know "notify about this status change" — not which channels
exist or how each one is contacted.

A notification failure (bad SMTP config, Twilio error, etc.) is caught
and logged here rather than allowed to propagate — sending a customer
notification is a nice-to-have side effect of a status update, and must
never be the reason the actual status update itself fails.
"""

"""
Sends a customer notification when a delivery's status changes, via
whichever channel(s) actually apply:
1. In-app notification (CustomerNotificationDB) — the REAL, primary
   channel: if this delivery is linked to a registered customer account
   (customer_id set), they see this the moment they open their
   dashboard, no email/phone/server access needed.
2. Email/SMS — a secondary, best-effort external channel for reaching
   someone even when they're not logged into the dashboard right now
   (or have no account at all). Uses the console-log-by-default pattern
   documented in email.py/sms.py.

Kept as its own thin module (rather than calling these three things
directly from the route/conflict-resolver code) so the call site only
needs to know "notify about this status change" — not which channels
exist or how each one is contacted.

A channel failure (bad SMTP config, Twilio error, etc.) is caught and
logged here rather than allowed to propagate — sending a notification is
a side effect of a status update, and must never be the reason the
actual status update itself fails.
"""

import os
from sqlalchemy.orm import Session

from app.services.email import send_status_notification_email
from app.services.sms import send_status_notification_sms, send_status_notification_whatsapp
from app.services.push import send_web_push
from app.services.expo_push import send_expo_push
from app.models.customer_notification import CustomerNotificationDB
from app.models.push_subscription import PushSubscriptionDB
from app.models.expo_push_token import ExpoPushTokenDB
from app.models.user import UserDB, UserRole

FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")

STATUS_LABELS = {
    "confirmed": "Order Confirmed",
    "picked_up": "Picked Up",
    "out_for_delivery": "Out for Delivery",
    "delivered": "Delivered",
    "failed_attempt": "Delivery Attempt Failed",
    "cancelled": "Order Cancelled",
    "partial_delivery": "Partially Delivered",
    "rescheduled": "Delivery Rescheduled",
    "rto_initiated": "Being Returned to Sender",
}


def notify_customer_of_status_change(
    db: Session,
    delivery_id: str,
    order_id: str,
    new_status: str,
    customer_email: str | None,
    customer_phone: str | None,
    customer_id: str | None = None,
) -> None:
    status_label = STATUS_LABELS.get(new_status, new_status)
    tracking_link = f"{FRONTEND_URL}/?track={delivery_id}"

    # 1. In-app notification — the real, primary channel
    if customer_id:
        try:
            notification = CustomerNotificationDB(
                customer_id=customer_id,
                delivery_id=delivery_id,
                order_id=order_id,
                message=f"Order {order_id} is now: {status_label}",
            )
            db.add(notification)
            db.commit()
        except Exception as error:  # noqa: BLE001
            print(f"In-app notification failed for {order_id}: {error}")

    # 2. Email — secondary, best-effort
    if customer_email:
        try:
            send_status_notification_email(customer_email, order_id, status_label, tracking_link)
        except Exception as error:  # noqa: BLE001
            print(f"Email notification failed for {order_id}: {error}")

    # 3. SMS — secondary, best-effort
    if customer_phone:
        try:
            send_status_notification_sms(customer_phone, order_id, status_label, tracking_link)
        except Exception as error:  # noqa: BLE001
            print(f"SMS notification failed for {order_id}: {error}")

    # 4. WhatsApp — secondary, best-effort (reuses the same Twilio
    # credentials as SMS above, via Twilio's free WhatsApp Sandbox)
    if customer_phone:
        try:
            send_status_notification_whatsapp(customer_phone, order_id, status_label, tracking_link)
        except Exception as error:  # noqa: BLE001
            print(f"WhatsApp notification failed for {order_id}: {error}")

    # 5. Web Push — real OS-level browser notification, works even with
    # the tab/browser closed. Needs no third-party account (unlike SMS/
    # WhatsApp above) since it's sent directly via VAPID, so this fires
    # for every subscribed device on file for this customer.
    if customer_id:
        try:
            subscriptions = db.query(PushSubscriptionDB).filter(
                PushSubscriptionDB.customer_id == customer_id
            ).all()
            for sub in subscriptions:
                send_web_push(
                    subscription_info={
                        "endpoint": sub.endpoint,
                        "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                    },
                    title=f"Order {order_id}",
                    body=status_label,
                    url=tracking_link,
                )
        except Exception as error:  # noqa: BLE001
            print(f"Web push notification failed for {order_id}: {error}")


def notify_customer_of_subscription_order_ready(db: Session, customer_id: str, order) -> None:
    """
    In-app notification (+ push, if subscribed) that a recurring order's
    next cycle is ready and waiting on payment. Deliberately doesn't
    reuse notify_customer_of_status_change above: there is no
    DeliveryRecordDB yet at this point (that's only created once the
    order is actually paid — see routes/checkout.py's verify_payment),
    so this notifies against the order_id alone rather than a
    delivery_id/status change. Same "never let a notification failure
    break the caller" treatment as the rest of this module.
    """
    tracking_link = f"{FRONTEND_URL}/?subscriptions=1"
    try:
        notification = CustomerNotificationDB(
            customer_id=customer_id,
            delivery_id="",
            order_id=order.id,
            message=f"Your recurring order is ready — ₹{order.total:.2f}. Confirm & pay to send it out.",
        )
        db.add(notification)
        db.commit()
    except Exception as error:  # noqa: BLE001
        print(f"Subscription in-app notification failed for {order.id}: {error}")

    try:
        subscriptions = db.query(PushSubscriptionDB).filter(
            PushSubscriptionDB.customer_id == customer_id
        ).all()
        for sub in subscriptions:
            send_web_push(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                title="Recurring order ready",
                body=f"₹{order.total:.2f} — confirm & pay to send it out.",
                url=tracking_link,
            )
    except Exception as error:  # noqa: BLE001
        print(f"Subscription push notification failed for {order.id}: {error}")


def _push_to_user_ids(db: Session, user_ids: list[str], title: str, body: str, url: str) -> None:
    """
    Shared low-level fan-out: sends one Web Push to every subscribed
    browser AND one Expo push to every registered mobile device, for a
    set of staff user IDs — every call site in this file (agent
    assignment/unassignment, dispatcher SLA alerts, etc.) automatically
    reaches the mobile agent app too, with no per-call-site change
    needed, the same way adding a new PushSubscriptionDB row already
    made Web Push "just work" for whichever staff member subscribed.
    `url` is passed through to Web Push as the click-through link (a
    web page); Expo push has no equivalent single field, since the
    mobile app itself already knows which screen to open, so it's
    simply omitted from the Expo call rather than forced into a
    `data` payload nothing in the app currently reads.
    """
    if not user_ids:
        return
    try:
        subscriptions = db.query(PushSubscriptionDB).filter(
            PushSubscriptionDB.user_id.in_(user_ids)
        ).all()
        for sub in subscriptions:
            send_web_push(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                title=title,
                body=body,
                url=url,
            )
    except Exception as error:  # noqa: BLE001
        print(f"Staff web push notification failed: {error}")

    try:
        expo_tokens = db.query(ExpoPushTokenDB).filter(
            ExpoPushTokenDB.user_id.in_(user_ids)
        ).all()
        for token_row in expo_tokens:
            send_expo_push(token_row.token, title=title, body=body)
    except Exception as error:  # noqa: BLE001
        print(f"Staff Expo push notification failed: {error}")


def notify_agent_of_new_assignment(db: Session, delivery_id: str, order_id: str, agent_id: str) -> None:
    """
    Web Push to one agent, the moment a delivery is assigned to them —
    either at dispatcher-creation time or via the "assign to agent"
    action on a customer-placed order. Best-effort: a missing/expired
    subscription (or the agent never having enabled push) is silently a
    no-op, same as the customer-facing push above.
    """
    tracking_link = f"{FRONTEND_URL}/?deliveries"
    _push_to_user_ids(
        db, [agent_id],
        title="New delivery assigned",
        body=f"Order {order_id} has been assigned to you.",
        url=tracking_link,
    )


def notify_agent_of_unassignment(db: Session, delivery_id: str, order_id: str, agent_id: str) -> None:
    """
    Web Push to an agent the moment a dispatcher pulls a delivery back
    off them and returns it to the unassigned pool — the mirror image
    of notify_agent_of_new_assignment(). Without this, an agent's only
    signal that an order disappeared would be it silently vanishing
    from their list on next refresh, which reads as a bug rather than
    a deliberate dispatcher action. Same best-effort semantics: a
    missing/expired push subscription is silently a no-op.
    """
    tracking_link = f"{FRONTEND_URL}/?deliveries"
    _push_to_user_ids(
        db, [agent_id],
        title="Delivery reassigned",
        body=f"Order {order_id} has been taken off your list and returned to dispatch.",
        url=tracking_link,
    )


def notify_dispatchers_of_sla_event(db: Session, org_id: str, order_id: str, event: str) -> None:
    """
    Web Push to every dispatcher/admin in an org when a delivery
    crosses an SLA threshold — `event` is "at_risk" (near-breach
    warning) or "breached". Mirrors notify_dispatchers_of_new_order
    exactly; kept as its own function since the copy differs and a
    future caller may want to filter/rate-limit SLA pushes separately
    from new-order pushes.
    """
    staff_ids = [
        row[0] for row in db.query(UserDB.id).filter(
            UserDB.org_id == org_id,
            UserDB.role.in_([UserRole.dispatcher, UserRole.admin]),
        ).all()
    ]
    tracking_link = f"{FRONTEND_URL}/?dashboard"
    if event == "breached":
        title, body = "SLA breached", f"Order {order_id} has missed its delivery SLA deadline."
    else:
        title, body = "SLA at risk", f"Order {order_id} is approaching its delivery SLA deadline."
    _push_to_user_ids(db, staff_ids, title=title, body=body, url=tracking_link)


def notify_customer_of_new_message(db: Session, delivery_id: str, order_id: str, customer_id: str, sender_display_name: str) -> None:
    """
    In-app + Web Push when a STAFF member sends a message on a
    delivery's chat thread — reuses the exact same two channels
    notify_customer_of_status_change already uses for the customer,
    since those are this project's real, working customer-notification
    channels (email/SMS/WhatsApp notification for every chat message
    would be noisy for a back-and-forth conversation the way it isn't
    for a one-off status change, so this deliberately uses fewer
    channels than that function does).
    """
    try:
        notification = CustomerNotificationDB(
            customer_id=customer_id, delivery_id=delivery_id, order_id=order_id,
            message=f"New message from {sender_display_name} about order {order_id}",
        )
        db.add(notification)
        db.commit()
    except Exception as error:  # noqa: BLE001
        print(f"In-app message notification failed for {order_id}: {error}")

    try:
        subscriptions = db.query(PushSubscriptionDB).filter(PushSubscriptionDB.customer_id == customer_id).all()
        for sub in subscriptions:
            send_web_push(
                subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
                title=f"Order {order_id}", body=f"{sender_display_name}: new message",
                url=f"{FRONTEND_URL}/?track={delivery_id}",
            )
    except Exception as error:  # noqa: BLE001
        print(f"Push message notification failed for {order_id}: {error}")


def notify_staff_of_new_message(db: Session, org_id: str, delivery_id: str, order_id: str, agent_id: str | None, sender_display_name: str) -> None:
    """
    Web Push to the delivery's assigned agent plus every dispatcher/
    admin in the org — mirrors notify_dispatchers_of_sla_event's
    staff-lookup pattern, just widened to also include the one agent
    (who isn't a dispatcher/admin, so wouldn't otherwise be in that query).
    """
    staff_ids = [
        row[0] for row in db.query(UserDB.id).filter(
            UserDB.org_id == org_id,
            UserDB.role.in_([UserRole.dispatcher, UserRole.admin]),
        ).all()
    ]
    if agent_id and agent_id not in staff_ids:
        staff_ids.append(agent_id)
    _push_to_user_ids(
        db, staff_ids, title=f"Order {order_id}", body=f"{sender_display_name}: new message",
        url=f"{FRONTEND_URL}/?dashboard",
    )


def notify_dispatchers_of_geofence_arrival(db: Session, org_id: str, order_id: str) -> None:
    """Web Push to dispatchers/admins when an agent's location ping lands within the delivery's arrival geofence (see services/route_analytics.py) — same staff-lookup pattern as notify_dispatchers_of_sla_event."""
    staff_ids = [
        row[0] for row in db.query(UserDB.id).filter(
            UserDB.org_id == org_id,
            UserDB.role.in_([UserRole.dispatcher, UserRole.admin]),
        ).all()
    ]
    _push_to_user_ids(
        db, staff_ids, title="Agent arriving", body=f"Agent has arrived near the delivery location for order {order_id}.",
        url=f"{FRONTEND_URL}/?dashboard",
    )


def notify_dispatchers_of_new_order(db: Session, org_id: str, order_id: str) -> None:
    """
    Web Push to every dispatcher AND admin in an org, the moment a new
    customer checkout order lands unassigned in their queue — so they
    don't have to keep the dashboard open/refreshing to notice it.
    """
    staff_ids = [
        row[0] for row in db.query(UserDB.id).filter(
            UserDB.org_id == org_id,
            UserDB.role.in_([UserRole.dispatcher, UserRole.admin]),
        ).all()
    ]
    tracking_link = f"{FRONTEND_URL}/?dashboard"
    _push_to_user_ids(
        db, staff_ids,
        title="New order to assign",
        body=f"Order {order_id} was just placed and needs an agent.",
        url=tracking_link,
    )
