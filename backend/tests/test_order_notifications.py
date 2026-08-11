import pytest

from application.order_notifications import (
    build_order_notification,
    deliver_order_notification_emails,
    notification_recipients,
)


def test_order_notification_contains_actionable_order_details():
    order = {
        "order_id": "np_ord_abc123",
        "total": 45.85,
        "address": {"full_name": "Jamie Moore", "email": "jamie@example.com"},
        "items": [{"name": "Sea Moss", "quantity": 2}],
    }
    notification = build_order_notification(order, "owner-1")
    assert notification["user_id"] == "owner-1"
    assert notification["type"] == "order_placed"
    assert "np_ord_abc123" in notification["message"]
    assert notification["metadata"]["order_id"] == "np_ord_abc123"
    assert notification["metadata"]["total"] == 45.85


def test_notification_recipients_deduplicate_ops_and_role_emails():
    users = [
        {"user_id": "owner-1", "email": "OWNER@example.com", "role": "owner", "is_active": True},
        {"user_id": "staff-1", "email": "staff@example.com", "role": "staff", "is_active": True},
        {"user_id": "customer-1", "email": "client@example.com", "role": "customer", "is_active": True},
    ]
    targets = notification_recipients(users, ops_email="owner@example.com")
    assert [target["user_id"] for target in targets["users"]] == ["owner-1", "staff-1"]
    assert targets["emails"] == ["owner@example.com", "staff@example.com"]


@pytest.mark.asyncio
async def test_order_email_delivery_does_not_require_celery_or_redis():
    class FakeEmail:
        def __init__(self):
            self.sent = []

        async def send_email(self, **payload):
            self.sent.append(payload)
            return {"success": True}

    email = FakeEmail()
    order = {
        "order_id": "np_ord_abc123",
        "total": 45.85,
        "address": {"full_name": "Jamie Moore"},
    }

    results = await deliver_order_notification_emails(
        email,
        ["owner@example.com", "staff@example.com"],
        order,
    )

    assert len(email.sent) == 2
    assert all(result["success"] for result in results)
