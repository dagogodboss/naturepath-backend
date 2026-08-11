"""Order operations notifications shared by checkout and tests."""

from __future__ import annotations

import asyncio
from html import escape
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


async def deliver_order_notification_emails(
    email_service: Any,
    emails: Iterable[str],
    order: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Send operations email directly so checkout alerts do not depend on Redis."""
    order_id = str(order["order_id"])
    total = float(order.get("total") or 0)
    customer = str((order.get("address") or {}).get("full_name") or "Customer")
    html = (
        f"<h2>New store order</h2><p>{escape(customer)} placed order "
        f"<strong>{escape(order_id)}</strong> for <strong>${total:.2f}</strong>.</p>"
        "<p>Open Store Operations to confirm or reject it.</p>"
    )
    tasks = [
        email_service.send_email(
            to_email=email,
            subject=f"New Natural Path order {order_id}",
            html_content=html,
            text_content=f"New order {order_id} from {customer} for ${total:.2f}.",
        )
        for email in emails
    ]
    return list(await asyncio.gather(*tasks)) if tasks else []


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

    from infrastructure.external.email_service import get_email_service
    await deliver_order_notification_emails(
        get_email_service(), targets["emails"], order
    )
    return len(notifications)
