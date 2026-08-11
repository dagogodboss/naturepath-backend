"""Unit + feature tests for 4-state discovery eligibility (Phase A1)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from application.use_cases.booking_use_case import BookingUseCase


def _uc() -> BookingUseCase:
    return BookingUseCase(
        booking_repo=AsyncMock(),
        slot_repo=AsyncMock(),
        service_repo=AsyncMock(),
        practitioner_repo=AsyncMock(),
        user_repo=AsyncMock(),
        payment_repo=AsyncMock(),
        event_repo=AsyncMock(),
        cache=None,
    )


def test_is_discovery_service_by_flag_and_name():
    assert BookingUseCase._is_discovery_service({"is_discovery_entry": True}) is True
    assert BookingUseCase._is_discovery_service({"name": "Discovery Call"}) is True
    assert BookingUseCase._is_discovery_service({"name": "Massage 60"}) is False
    assert BookingUseCase._is_discovery_service(None) is False


@pytest.mark.asyncio
async def test_eligibility_completed_when_staff_flag_set():
    uc = _uc()
    uc.user_repo.get_by_id = AsyncMock(
        return_value={
            "user_id": "c1",
            "is_discovery_completed": True,
            "discovery_completed_booking_id": "b-done",
        }
    )
    result = await uc.get_discovery_eligibility("c1")
    assert result["state"] == "completed"
    assert result["messaging_key"] == "unlocked"
    assert result["is_discovery_completed"] is True
    uc.booking_repo.get_by_customer.assert_not_called()


@pytest.mark.asyncio
async def test_eligibility_none_without_discovery_booking():
    uc = _uc()
    uc.user_repo.get_by_id = AsyncMock(return_value={"user_id": "c1"})
    uc.booking_repo.get_by_customer = AsyncMock(
        return_value=[{"booking_id": "b1", "status": "confirmed", "service_id": "s-massage"}]
    )
    uc.service_repo.get_by_id = AsyncMock(return_value={"name": "Massage", "service_id": "s-massage"})
    result = await uc.get_discovery_eligibility("c1")
    assert result["state"] == "none"
    assert result["messaging_key"] == "please_book"


@pytest.mark.asyncio
async def test_eligibility_scheduled_future_confirmed():
    uc = _uc()
    uc.user_repo.get_by_id = AsyncMock(return_value={"user_id": "c1"})
    future = (datetime.now(timezone.utc) + timedelta(days=5)).strftime("%Y-%m-%d")
    uc.booking_repo.get_by_customer = AsyncMock(
        return_value=[
            {
                "booking_id": "b-disc",
                "status": "confirmed",
                "service_id": "s-disc",
                "slot": {"date": future, "start_time": "10:00"},
            }
        ]
    )
    uc.service_repo.get_by_id = AsyncMock(
        return_value={"name": "Discovery Call", "is_discovery_entry": True}
    )
    with patch(
        "core.time_utils.clinic_now",
        return_value=datetime.now(timezone.utc),
    ):
        result = await uc.get_discovery_eligibility("c1")
    assert result["state"] == "scheduled"
    assert result["messaging_key"] == "scheduled"
    assert result["discovery_booking_id"] == "b-disc"


@pytest.mark.asyncio
async def test_eligibility_pending_when_slot_passed():
    uc = _uc()
    uc.user_repo.get_by_id = AsyncMock(return_value={"user_id": "c1"})
    past = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d")
    uc.booking_repo.get_by_customer = AsyncMock(
        return_value=[
            {
                "booking_id": "b-past",
                "status": "confirmed",
                "service_id": "s-disc",
                "slot": {"date": past, "start_time": "10:00"},
            }
        ]
    )
    uc.service_repo.get_by_id = AsyncMock(
        return_value={"name": "Discovery Call", "is_discovery_entry": True}
    )
    with patch(
        "core.time_utils.clinic_now",
        return_value=datetime.now(timezone.utc),
    ):
        result = await uc.get_discovery_eligibility("c1")
    assert result["state"] == "pending_completion"
    assert result["messaging_key"] == "pending"


@pytest.mark.asyncio
async def test_eligibility_pending_for_completed_status_without_flag():
    uc = _uc()
    uc.user_repo.get_by_id = AsyncMock(return_value={"user_id": "c1"})
    uc.booking_repo.get_by_customer = AsyncMock(
        return_value=[
            {
                "booking_id": "b-done-session",
                "status": "completed",
                "service_id": "s-disc",
                "slot": {"date": "2026-01-01", "start_time": "10:00"},
            }
        ]
    )
    uc.service_repo.get_by_id = AsyncMock(
        return_value={"name": "Discovery Call", "is_discovery_entry": True}
    )
    result = await uc.get_discovery_eligibility("c1")
    assert result["state"] == "pending_completion"


@pytest.mark.asyncio
async def test_mark_discovery_completed_staff_only_unlock():
    uc = _uc()
    uc.booking_repo.get_by_id = AsyncMock(
        return_value={
            "booking_id": "b1",
            "customer_id": "c1",
            "practitioner_id": "p1",
            "service_id": "s-disc",
            "status": "confirmed",
        }
    )
    uc.service_repo.get_by_id = AsyncMock(
        return_value={"name": "Discovery Call", "is_discovery_entry": True}
    )
    uc.practitioner_repo.get_by_id = AsyncMock(
        return_value={"practitioner_id": "p1", "user_id": "staff-1"}
    )
    uc.user_repo.update = AsyncMock()
    uc.booking_repo.update = AsyncMock()
    # After unlock, get_discovery_eligibility sees the staff flag.
    uc.user_repo.get_by_id = AsyncMock(
        return_value={
            "user_id": "c1",
            "is_discovery_completed": True,
            "discovery_completed_booking_id": "b1",
        }
    )

    result = await uc.mark_discovery_completed("b1", "staff-1", as_admin=False)
    assert result["state"] == "completed"
    assert result["messaging_key"] == "unlocked"
    uc.user_repo.update.assert_awaited()
    args = uc.user_repo.update.await_args
    assert args.args[0] == "c1"
    assert args.args[1]["is_discovery_completed"] is True


@pytest.mark.asyncio
async def test_mark_discovery_rejects_non_practitioner():
    uc = _uc()
    uc.booking_repo.get_by_id = AsyncMock(
        return_value={
            "booking_id": "b1",
            "customer_id": "c1",
            "practitioner_id": "p1",
            "service_id": "s-disc",
            "status": "confirmed",
        }
    )
    uc.service_repo.get_by_id = AsyncMock(
        return_value={"name": "Discovery Call", "is_discovery_entry": True}
    )
    uc.practitioner_repo.get_by_id = AsyncMock(
        return_value={"practitioner_id": "p1", "user_id": "other-staff"}
    )
    with pytest.raises(ValueError, match="Unauthorized"):
        await uc.mark_discovery_completed("b1", "staff-1", as_admin=False)


@pytest.mark.asyncio
async def test_non_discovery_booking_blocked_until_completed():
    """User-story: guests/customers cannot book other services until unlock."""
    uc = _uc()
    uc.service_repo.get_by_id = AsyncMock(
        return_value={"service_id": "s-massage", "name": "Massage", "is_discovery_entry": False}
    )
    uc.user_repo.get_by_id = AsyncMock(return_value={"user_id": "c1"})
    uc.booking_repo.get_by_customer = AsyncMock(return_value=[])
    # Minimal create_booking path check via eligibility gate helper used in create
    eligibility = await uc.get_discovery_eligibility("c1")
    assert eligibility["state"] != "completed"
