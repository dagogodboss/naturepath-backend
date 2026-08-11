"""Order operations notifications shared by checkout and tests."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

from domain.entities import generate_id


OPS_ROLES = {"owner", "admin", "manager", "staff"}


def notification_recipients(
    users: Iterable[Dict[str, Any]],
    *,
    ops_email: str | None = None,
) -> Dict[str, List[Any]]:
    selected = [
        user
        for user in users
        if user.get("is_active", True) and str(user.get("role") or "").lower() in OPS_ROLES
    ]
    emails: List[str] = []
    seen = set()
    for raw in [ops_email, *(user.get("email") for user in selected)]:
        email = str(raw or "").strip().lower()
        if email and email not in seen:
            seen.add(email)
            emails.append(email)
    return {"users": selected, "emails": emails}


def build_order_notification(order: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    order_id = str(order["order_id"])
    customer = str((order.get("address") or {}).get("full_name") or "A customer")
    total = float(order.get("total") or 0)
    now = datetime.now(timezone.utc).isoformat()
    return {
        "notification_id": generate_id(),
        "user_id": user_id,
        "type": "order_placed",
        "title": "New store order",
        "message": f"{customer} placed order {order_id} for ${total:.2f}.",
        "is_read": False,
        "metadata": {"order_id": order_id, "total": total, "route": "/practitioner/store"},
        "sent_email": False,
        "sent_sms": False,
        "created_at": now,
    }


async def queue_order_notifications(db: Any, order: Dict[str, Any], *, ops_email: str | None) -> int:
    users = await db.users.find(
        {"role": {"$in": sorted(OPS_ROLES)}, "is_active": {"$ne": False}},
        {"_id": 0, "user_id": 1, "email": 1, "role": 1, "is_active": 1},
    ).to_list(length=500)
    targets = notification_recipients(users, ops_email=ops_email)
    notifications = [build_order_notification(order, user["user_id"]) for user in targets["users"]]
    if notifications:
        await db.notifications.insert_many(notifications)

    from presentation.websockets.handlers import get_connection_manager
    manager = get_connection_manager()
    for notification in notifications:
        await manager.send_user_notification(
            notification["user_id"],
            "order_placed",
            notification,
        )

    from workers.notification_worker import send_generic_email
    order_id = order["order_id"]
    total = float(order.get("total") or 0)
    customer = (order.get("address") or {}).get("full_name") or "Customer"
    for email in targets["emails"]:
        send_generic_email.delay(
            email,
            f"New Natural Path order {order_id}",
            (
                f"<h2>New store order</h2><p>{customer} placed order "
                f"<strong>{order_id}</strong> for <strong>${total:.2f}</strong>.</p>"
                "<p>Open Store Operations to confirm or reject it.</p>"
            ),
            f"New order {order_id} from {customer} for ${total:.2f}.",
        )
    return len(notifications)

