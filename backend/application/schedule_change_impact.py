"""
Schedule-change impact preview + review enqueue (Q7).

When admin tightens resource hours, last_start, or service scheduling, find
confirmed future bookings that would no longer fit — preview only or enqueue
schedule_change_impact review items. Never auto-cancel or rewrite payments.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Mapping, Optional, Sequence

from application.availability_explain import (
    OCCUPATION_OVERFLOW,
    RESOURCE_HOURS_CLOSED,
    SERVICE_WEEKDAY_CLOSED,
    explain_availability,
)
from application.multi_resource_booking import (
    effective_last_start_time,
    occupied_times_for_session,
)
from application.multi_resource_slots import minutes_from_hhmm
from domain.entities.models import (
    ReviewQueueItemStatus,
    ReviewQueueItemType,
    generate_id,
    utc_now,
)

logger = logging.getLogger(__name__)

SCHEDULE_CHANGE_MESSAGE = (
    "Confirmed booking may fall outside new schedule rules; "
    "staff review required (Q7)."
)

SCHEDULE_IMPACT_REASON_CODES = frozenset(
    {
        RESOURCE_HOURS_CLOSED,
        OCCUPATION_OVERFLOW,
        SERVICE_WEEKDAY_CLOSED,
        "LAST_START_EXCEEDED",
    }
)


def _booking_slot_date(booking: Mapping[str, Any]) -> Optional[str]:
    slot = booking.get("slot") or {}
    raw = slot.get("date") or booking.get("date")
    return str(raw).strip() if raw else None


def _booking_session_start(booking: Mapping[str, Any]) -> Optional[str]:
    slot = booking.get("slot") or {}
    raw = slot.get("start_time") or booking.get("customer_start_time")
    return str(raw).strip() if raw else None


def _merge_resource(
    existing: Mapping[str, Any], patch: Mapping[str, Any]
) -> dict[str, Any]:
    merged = dict(existing)
    merged.update(patch)
    return merged


def _merge_service(
    existing: Mapping[str, Any], patch: Mapping[str, Any]
) -> dict[str, Any]:
    merged = dict(existing)
    merged.update(patch)
    return merged


def _last_start_violation(
    *,
    resource: Mapping[str, Any],
    service: Mapping[str, Any],
    start_time: str,
) -> Optional[dict[str, Any]]:
    eff = effective_last_start_time(resource, service)
    if not eff:
        return None
    try:
        if minutes_from_hhmm(start_time) > minutes_from_hhmm(eff):
            return {
                "code": "LAST_START_EXCEEDED",
                "message": (
                    f"Session start {start_time} is after last bookable start {eff}"
                ),
                "details": {
                    "start_time": start_time,
                    "last_start_time": eff,
                },
            }
    except ValueError:
        return None
    return None


def evaluate_booking_schedule_impact(
    *,
    booking: Mapping[str, Any],
    service: Mapping[str, Any],
    resource: Mapping[str, Any],
) -> Optional[dict[str, Any]]:
    """
    Return an impact row when a confirmed booking would not fit under resource+service
    rules (hours / last_start / service weekday flags). Ignores Outlook busy.
    """
    date_str = _booking_slot_date(booking)
    start_time = _booking_session_start(booking)
    if not date_str or not start_time:
        return None

    explained = explain_availability(
        date_str=date_str,
        service=service,
        resource=resource,
        busy_intervals=(),
        start_time=start_time,
        sync_stale=False,
    )
    reasons = [
        r
        for r in explained.get("reasons") or []
        if r.get("code") in SCHEDULE_IMPACT_REASON_CODES
    ]
    extra = _last_start_violation(
        resource=resource, service=service, start_time=start_time
    )
    if extra and not any(r.get("code") == "LAST_START_EXCEEDED" for r in reasons):
        reasons.append(extra)

    if not reasons:
        return None

    occupied = booking.get("occupied_start_time"), booking.get("occupied_end_time")
    if not occupied[0] or not occupied[1]:
        try:
            occ = occupied_times_for_session(service, start_time)
            occupied = occ["start_time"], occ["end_time"]
        except (ValueError, KeyError):
            occupied = (None, None)

    slot = booking.get("slot") or {}
    return {
        "booking_id": booking.get("booking_id"),
        "service_id": booking.get("service_id") or service.get("service_id"),
        "resource_id": resource.get("resource_id") or booking.get("resource_id"),
        "slot": {
            "date": date_str,
            "start_time": start_time,
            "end_time": slot.get("end_time"),
        },
        "occupied": {
            "start_time": occupied[0],
            "end_time": occupied[1],
        },
        "reasons": reasons,
    }


def _future_confirmed(bookings: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    today = date.today().isoformat()
    out: list[Mapping[str, Any]] = []
    for row in bookings:
        if str(row.get("status") or "").lower() != "confirmed":
            continue
        d = _booking_slot_date(row)
        if not d or d < today:
            continue
        out.append(row)
    return out


async def _load_services_map(db: Any, service_ids: Sequence[str]) -> dict[str, dict]:
    services_col = getattr(db, "services", None)
    if services_col is None or not service_ids:
        return {}
    out: dict[str, dict] = {}
    for sid in service_ids:
        if not sid or sid in out:
            continue
        try:
            doc = await services_col.find_one({"service_id": sid}, {"_id": 0})
        except Exception:
            doc = None
        if doc:
            out[sid] = dict(doc)
    return out


async def compute_resource_schedule_impact(
    db: Any,
    *,
    resource_id: str,
    existing_resource: Mapping[str, Any],
    proposed_patch: Mapping[str, Any],
) -> dict[str, Any]:
    merged_resource = _merge_resource(existing_resource, proposed_patch)
    bookings_col = getattr(db, "bookings", None)
    items: list[dict[str, Any]] = []
    if bookings_col is None:
        # Missing collection is unknown impact, not "zero bookings affected" (#9 C2).
        return {
            "resource_id": resource_id,
            "affected_count": None,
            "items": items,
            "impact_unknown": True,
            "message": "Unable to load confirmed bookings; schedule impact is unknown.",
            "phase": "schedule_change_preview",
        }

    try:
        rows = await bookings_col.find(
            {"status": "confirmed", "resource_id": resource_id},
            {"_id": 0},
        ).to_list(length=2000)
    except Exception:
        logger.exception("Failed to load bookings for resource %s", resource_id)
        return {
            "resource_id": resource_id,
            "affected_count": None,
            "items": items,
            "impact_unknown": True,
            "message": "Unable to load confirmed bookings; schedule impact is unknown.",
            "phase": "schedule_change_preview",
        }

    future = _future_confirmed(rows)
    service_ids = [str(b.get("service_id") or "") for b in future]
    services = await _load_services_map(db, service_ids)

    for booking in future:
        sid = str(booking.get("service_id") or "")
        service = services.get(sid)
        if not service:
            service = {
                "service_id": sid,
                "duration_minutes": int(booking.get("duration_minutes") or 60),
                "prep_minutes": 0,
                "recovery_minutes": 0,
            }
        hit = evaluate_booking_schedule_impact(
            booking=booking,
            service=service,
            resource=merged_resource,
        )
        if hit:
            items.append(hit)

    return {
        "resource_id": resource_id,
        "affected_count": len(items),
        "items": items,
        "impact_unknown": False,
        "phase": "schedule_change_preview",
    }


async def compute_service_scheduling_impact(
    db: Any,
    *,
    service_id: str,
    existing_service: Mapping[str, Any],
    proposed_patch: Mapping[str, Any],
) -> dict[str, Any]:
    merged_service = _merge_service(existing_service, proposed_patch)
    bookings_col = getattr(db, "bookings", None)
    items: list[dict[str, Any]] = []
    if bookings_col is None:
        return {
            "service_id": service_id,
            "affected_count": None,
            "items": items,
            "impact_unknown": True,
            "message": "Unable to load confirmed bookings; schedule impact is unknown.",
            "phase": "schedule_change_preview",
        }

    try:
        rows = await bookings_col.find(
            {"status": "confirmed", "service_id": service_id},
            {"_id": 0},
        ).to_list(length=2000)
    except Exception:
        logger.exception("Failed to load bookings for service %s", service_id)
        return {
            "service_id": service_id,
            "affected_count": None,
            "items": items,
            "impact_unknown": True,
            "message": "Unable to load confirmed bookings; schedule impact is unknown.",
            "phase": "schedule_change_preview",
        }

    future = _future_confirmed(rows)
    resource_ids = set()
    for b in future:
        rid = merged_service.get("required_resource_id") or b.get("resource_id")
        if rid:
            resource_ids.add(str(rid))

    resources: dict[str, dict] = {}
    res_col = getattr(db, "resources", None)
    if res_col is not None:
        for rid in resource_ids:
            try:
                doc = await res_col.find_one({"resource_id": rid}, {"_id": 0})
            except Exception:
                doc = None
            if doc:
                resources[rid] = dict(doc)

    for booking in future:
        rid = str(
            merged_service.get("required_resource_id")
            or booking.get("resource_id")
            or ""
        )
        resource = resources.get(rid) or {"resource_id": rid, "weekly_hours": []}
        hit = evaluate_booking_schedule_impact(
            booking=booking,
            service=merged_service,
            resource=resource,
        )
        if hit:
            items.append(hit)

    return {
        "service_id": service_id,
        "affected_count": len(items),
        "items": items,
        "impact_unknown": False,
        "phase": "schedule_change_preview",
    }


async def upsert_schedule_change_impact_review(
    db: Any,
    *,
    booking: Mapping[str, Any],
    impact_row: Mapping[str, Any],
    change_kind: str,
) -> Optional[str]:
    review_col = getattr(db, "review_queue", None)
    if review_col is None:
        return None

    booking_id = str(booking.get("booking_id") or "")
    if not booking_id:
        return None

    date_str = _booking_slot_date(booking) or ""
    start_time = _booking_session_start(booking) or ""
    resource_id = impact_row.get("resource_id") or booking.get("resource_id")

    query: dict[str, Any] = {
        "booking_id": booking_id,
        "type": ReviewQueueItemType.SCHEDULE_CHANGE_IMPACT.value,
        "status": ReviewQueueItemStatus.OPEN.value,
        "payload.slot.date": date_str,
        "payload.slot.start_time": start_time,
    }
    if resource_id:
        query["resource_id"] = resource_id

    try:
        existing = await review_col.find_one(query, {"_id": 0})
    except Exception:
        existing = None

    now = utc_now()
    now_iso = now.isoformat() if hasattr(now, "isoformat") else str(now)

    payload = {
        "change_kind": change_kind,
        "slot": dict(impact_row.get("slot") or {}),
        "occupied": dict(impact_row.get("occupied") or {}),
        "reasons": list(impact_row.get("reasons") or []),
    }

    if existing and existing.get("review_id"):
        return str(existing["review_id"])

    review_id = generate_id()
    doc = {
        "review_id": review_id,
        "type": ReviewQueueItemType.SCHEDULE_CHANGE_IMPACT.value,
        "status": ReviewQueueItemStatus.OPEN.value,
        "resource_id": resource_id,
        "connection_id": None,
        "event_id": None,
        "booking_id": booking_id,
        "message": SCHEDULE_CHANGE_MESSAGE,
        "payload": payload,
        "created_at": now_iso,
        "resolved_at": None,
    }
    try:
        await review_col.insert_one(doc)
    except Exception:
        logger.exception(
            "Failed to insert schedule_change_impact review for %s", booking_id
        )
        return None
    return review_id


async def enqueue_schedule_change_reviews(
    db: Any,
    *,
    impact: Mapping[str, Any],
    bookings_by_id: Mapping[str, Mapping[str, Any]],
    change_kind: str,
) -> int:
    enqueued = 0
    for row in impact.get("items") or []:
        bid = str(row.get("booking_id") or "")
        booking = bookings_by_id.get(bid)
        if not booking:
            continue
        rid = await upsert_schedule_change_impact_review(
            db,
            booking=booking,
            impact_row=row,
            change_kind=change_kind,
        )
        if rid:
            enqueued += 1
    return enqueued
