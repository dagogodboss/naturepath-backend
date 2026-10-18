"""
Phase 4–5 admin scheduling API scaffold.

Routes are always registered so OpenAPI can list them in non-prod builds, but every
handler returns 404 when settings.multi_resource_scheduling is False. Production
keeps the flag off — unfinished scheduling admin stays inert.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from application.availability_explain import (
    SYNC_STALE_AFTER_MINUTES,
    explain_availability as explain_slot,
    sync_is_stale,
)
from application.multi_resource_conflicts import enqueue_sync_conflicts_for_busy_intervals
from application.schedule_change_impact import (
    compute_resource_schedule_impact,
    compute_service_scheduling_impact,
    enqueue_schedule_change_reviews,
)
from core.config import settings
from domain.entities.models import (
    BusyIntervalSource,
    OutlookCategoryMap,
    PractitionerAvailability,
    generate_id,
)
from domain.multi_resource_defaults import build_locked_outlook_connection_templates
from infrastructure.database import get_database
from presentation.dependencies import get_current_admin_or_practitioner

router = APIRouter(tags=["Admin Scheduling"])


def _require_multi_resource_scheduling() -> None:
    """Hide unfinished Phase 4 APIs when the feature flag is off."""
    if not settings.multi_resource_scheduling:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---- request bodies ---------------------------------------------------------


class ResourceUpdate(BaseModel):
    """Partial update for a resource (weekly hours are the Phase 4 MVP focus)."""

    weekly_hours: Optional[List[PractitionerAvailability]] = None
    last_start_time: Optional[str] = Field(
        default=None,
        description="HH:MM clinic-local; last bookable session start (e.g. Salt 17:00)",
    )
    active: Optional[bool] = None
    name: Optional[str] = None
    timezone: Optional[str] = None


class ServiceSchedulingUpdate(BaseModel):
    required_resource_id: Optional[str] = None
    prep_minutes: Optional[int] = Field(default=None, ge=0)
    recovery_minutes: Optional[int] = Field(default=None, ge=0)
    customer_duration_minutes: Optional[int] = Field(default=None, ge=1)
    min_notice_minutes: Optional[int] = Field(default=None, ge=0)
    booking_window_days: Optional[int] = Field(default=None, ge=1)
    service_hours: Optional[List[PractitionerAvailability]] = None
    flags: Optional[dict] = None


class CategoryMapsPut(BaseModel):
    category_maps: List[OutlookCategoryMap] = Field(default_factory=list)


class OutlookConnectionSettingsUpdate(BaseModel):
    """Safe admin fields only — never tokens or OAuth secrets."""

    authoritative_for_resource_ids: Optional[List[str]] = None
    visibility_only: Optional[bool] = None
    is_active: Optional[bool] = None
    mailbox_email: Optional[str] = Field(
        default=None,
        description="Display label for admin UI; does not re-OAuth",
    )


class ReviewQueueResolveBody(BaseModel):
    """Optional admin note when resolving a review item."""

    note: Optional[str] = Field(default=None, max_length=2000)


class ReviewQueueDismissBody(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=2000)


class ManualBusyIntervalUpsert(BaseModel):
    """Admin manual block on a resource (maintenance, hold, etc.)."""

    date: str = Field(..., description="YYYY-MM-DD clinic-local")
    start_time: str = Field(..., description="HH:MM occupied start")
    end_time: str = Field(..., description="HH:MM occupied end")
    authoritative: bool = True
    show_as: str = "busy"
    is_cancelled: bool = False
    note: Optional[str] = Field(default=None, max_length=2000)


# ---- helpers ----------------------------------------------------------------


def _resource_public(doc: dict) -> dict:
    return {
        "resource_id": doc.get("resource_id"),
        "type": doc.get("type"),
        "name": doc.get("name"),
        "timezone": doc.get("timezone", "America/Chicago"),
        "active": bool(doc.get("active", True)),
        "weekly_hours": doc.get("weekly_hours") or [],
        "linked_practitioner_id": doc.get("linked_practitioner_id"),
        "linked_practitioner_user_id": doc.get("linked_practitioner_user_id"),
        "slot_grid": doc.get("slot_grid"),
        "last_start_time": doc.get("last_start_time"),
        "capacity": doc.get("capacity", 1),
        "updated_at": doc.get("updated_at"),
    }


def _service_scheduling_public(doc: dict) -> dict:
    return {
        "service_id": doc.get("service_id"),
        "name": doc.get("name"),
        "duration_minutes": doc.get("duration_minutes"),
        "required_resource_id": doc.get("required_resource_id"),
        "customer_duration_minutes": doc.get("customer_duration_minutes"),
        "prep_minutes": int(doc.get("prep_minutes") or 0),
        "recovery_minutes": int(doc.get("recovery_minutes") or 0),
        "min_notice_minutes": doc.get("min_notice_minutes"),
        "booking_window_days": doc.get("booking_window_days"),
        "service_hours": doc.get("service_hours"),
        "flags": doc.get("flags") or {},
    }


# ---- Section 1 — Resources & hours ------------------------------------------


@router.get("/resources", response_model=dict)
async def list_resources(
    ctx: dict = Depends(get_current_admin_or_practitioner),
    db=Depends(get_database),
):
    _require_multi_resource_scheduling()
    rows = await db.resources.find({}, {"_id": 0}).to_list(500)
    return {"items": [_resource_public(r) for r in rows]}


def _resource_patch_from_body(body: ResourceUpdate) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    if body.weekly_hours is not None:
        patch["weekly_hours"] = [h.model_dump() for h in body.weekly_hours]
    if body.active is not None:
        patch["active"] = body.active
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="name must not be empty",
            )
        patch["name"] = name
    if body.timezone is not None:
        patch["timezone"] = body.timezone
    fields_set = set(getattr(body, "model_fields_set", set()))
    if "last_start_time" in fields_set:
        lst = (body.last_start_time or "").strip()
        patch["last_start_time"] = lst or None
    return patch


@router.post("/resources/{resource_id}/schedule-change-preview", response_model=dict)
async def preview_resource_schedule_change(
    resource_id: str,
    body: ResourceUpdate,
    ctx: dict = Depends(get_current_admin_or_practitioner),
    db=Depends(get_database),
):
    """Impact preview only — does not persist resource changes."""
    _require_multi_resource_scheduling()
    existing = await db.resources.find_one({"resource_id": resource_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
    patch = _resource_patch_from_body(body)
    if not patch:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields to preview",
        )
    return await compute_resource_schedule_impact(
        db,
        resource_id=resource_id,
        existing_resource=existing,
        proposed_patch=patch,
    )


@router.patch("/resources/{resource_id}", response_model=dict)
async def update_resource(
    resource_id: str,
    body: ResourceUpdate,
    preview: bool = Query(False, description="When true, return impact without saving"),
    enqueue_reviews: bool = Query(
        True,
        description="When saving, enqueue schedule_change_impact reviews for affected bookings",
    ),
    ctx: dict = Depends(get_current_admin_or_practitioner),
    db=Depends(get_database),
):
    _require_multi_resource_scheduling()
    existing = await db.resources.find_one({"resource_id": resource_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")

    patch = _resource_patch_from_body(body)
    if not patch:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields to update",
        )

    impact = await compute_resource_schedule_impact(
        db,
        resource_id=resource_id,
        existing_resource=existing,
        proposed_patch=patch,
    )
    if preview:
        return {
            **_resource_public({**existing, **patch}),
            "schedule_change_impact": impact,
            "saved": False,
        }

    patch["updated_at"] = _utc_now()
    await db.resources.update_one({"resource_id": resource_id}, {"$set": patch})
    updated = await db.resources.find_one({"resource_id": resource_id}, {"_id": 0})
    reviews_enqueued = 0
    if enqueue_reviews and impact.get("affected_count"):
        bookings_by_id: dict[str, Any] = {}
        bookings_col = getattr(db, "bookings", None)
        if bookings_col is not None:
            for row in impact.get("items") or []:
                bid = str(row.get("booking_id") or "")
                if not bid or bid in bookings_by_id:
                    continue
                try:
                    doc = await bookings_col.find_one({"booking_id": bid}, {"_id": 0})
                except Exception:
                    doc = None
                if doc:
                    bookings_by_id[bid] = doc
        reviews_enqueued = await enqueue_schedule_change_reviews(
            db,
            impact=impact,
            bookings_by_id=bookings_by_id,
            change_kind="resource_hours",
        )
    return {
        **_resource_public(updated or {**existing, **patch}),
        "schedule_change_impact": impact,
        "schedule_change_reviews_enqueued": reviews_enqueued,
        "saved": True,
    }


# ---- Section 2 — Services & durations ---------------------------------------


@router.get("/services/{service_id}/scheduling", response_model=dict)
async def get_service_scheduling(
    service_id: str,
    ctx: dict = Depends(get_current_admin_or_practitioner),
    db=Depends(get_database),
):
    _require_multi_resource_scheduling()
    doc = await db.services.find_one({"service_id": service_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")
    return _service_scheduling_public(doc)


async def _service_scheduling_patch_from_body(
    db,
    body: ServiceSchedulingUpdate,
) -> dict[str, Any]:
    fields_set = set(getattr(body, "model_fields_set", set()))
    if not fields_set:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields to update",
        )

    patch: dict[str, Any] = {}
    if "required_resource_id" in fields_set:
        rid = body.required_resource_id
        if rid:
            resource = await db.resources.find_one({"resource_id": rid}, {"_id": 0})
            if not resource:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Unknown required_resource_id: {rid}",
                )
        patch["required_resource_id"] = rid
    if "prep_minutes" in fields_set and body.prep_minutes is not None:
        patch["prep_minutes"] = body.prep_minutes
    if "recovery_minutes" in fields_set and body.recovery_minutes is not None:
        patch["recovery_minutes"] = body.recovery_minutes
    if "customer_duration_minutes" in fields_set and body.customer_duration_minutes is not None:
        patch["customer_duration_minutes"] = body.customer_duration_minutes
    if "min_notice_minutes" in fields_set:
        patch["min_notice_minutes"] = body.min_notice_minutes
    if "booking_window_days" in fields_set:
        patch["booking_window_days"] = body.booking_window_days
    if "service_hours" in fields_set:
        patch["service_hours"] = (
            [h.model_dump() for h in body.service_hours] if body.service_hours is not None else None
        )
    if "flags" in fields_set and body.flags is not None:
        patch["flags"] = body.flags

    if not patch:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields to update",
        )
    return patch


@router.post("/services/{service_id}/scheduling-preview", response_model=dict)
async def preview_service_scheduling_change(
    service_id: str,
    body: ServiceSchedulingUpdate,
    ctx: dict = Depends(get_current_admin_or_practitioner),
    db=Depends(get_database),
):
    _require_multi_resource_scheduling()
    existing = await db.services.find_one({"service_id": service_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")
    patch = await _service_scheduling_patch_from_body(db, body)
    return await compute_service_scheduling_impact(
        db,
        service_id=service_id,
        existing_service=existing,
        proposed_patch=patch,
    )


@router.patch("/services/{service_id}/scheduling", response_model=dict)
async def patch_service_scheduling(
    service_id: str,
    body: ServiceSchedulingUpdate,
    preview: bool = Query(False, description="When true, return impact without saving"),
    enqueue_reviews: bool = Query(
        True,
        description="When saving, enqueue schedule_change_impact reviews for affected bookings",
    ),
    ctx: dict = Depends(get_current_admin_or_practitioner),
    db=Depends(get_database),
):
    _require_multi_resource_scheduling()
    existing = await db.services.find_one({"service_id": service_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")

    patch = await _service_scheduling_patch_from_body(db, body)
    impact = await compute_service_scheduling_impact(
        db,
        service_id=service_id,
        existing_service=existing,
        proposed_patch=patch,
    )
    if preview:
        return {
            **_service_scheduling_public({**existing, **patch}),
            "schedule_change_impact": impact,
            "saved": False,
        }

    patch["updated_at"] = _utc_now()
    await db.services.update_one({"service_id": service_id}, {"$set": patch})
    updated = await db.services.find_one({"service_id": service_id}, {"_id": 0})
    reviews_enqueued = 0
    if enqueue_reviews and impact.get("affected_count"):
        bookings_by_id: dict[str, Any] = {}
        bookings_col = getattr(db, "bookings", None)
        if bookings_col is not None:
            for row in impact.get("items") or []:
                bid = str(row.get("booking_id") or "")
                if not bid or bid in bookings_by_id:
                    continue
                try:
                    doc = await bookings_col.find_one({"booking_id": bid}, {"_id": 0})
                except Exception:
                    doc = None
                if doc:
                    bookings_by_id[bid] = doc
        reviews_enqueued = await enqueue_schedule_change_reviews(
            db,
            impact=impact,
            bookings_by_id=bookings_by_id,
            change_kind="service_scheduling",
        )
    return {
        **_service_scheduling_public(updated or {**existing, **patch}),
        "schedule_change_impact": impact,
        "schedule_change_reviews_enqueued": reviews_enqueued,
        "saved": True,
    }


# ---- Manual resource busy (Q7 sync_conflict enqueue) ------------------------


async def _upsert_manual_busy_interval(
    db,
    *,
    resource_id: str,
    interval_id: str,
    body: ManualBusyIntervalUpsert,
) -> tuple[dict, int]:
    """
    Persist source=manual busy and enqueue sync_conflict reviews for overlaps.

    Never mutates bookings or payments. Returns (saved_interval, enqueued_count).
    """
    busy_col = getattr(db, "resource_busy_intervals", None)
    if busy_col is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    existing = await busy_col.find_one({"interval_id": interval_id}, {"_id": 0})
    if existing:
        if str(existing.get("resource_id") or "") != resource_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Busy interval not found",
            )
        existing_source = str(existing.get("source") or "").lower()
        if existing_source != BusyIntervalSource.MANUAL.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only manual busy intervals can be edited here",
            )

    now = _utc_now()
    doc: dict[str, Any] = {
        "interval_id": interval_id,
        "resource_id": resource_id,
        "date": body.date.strip(),
        "start_time": body.start_time.strip(),
        "end_time": body.end_time.strip(),
        "source": BusyIntervalSource.MANUAL.value,
        "authoritative": bool(body.authoritative),
        "show_as": (body.show_as or "busy").strip().lower() or "busy",
        "is_cancelled": bool(body.is_cancelled),
        "connection_id": None,
        "event_id": None,
        "booking_id": None,
        "synced_at": now,
        "updated_at": now,
    }
    if body.note:
        doc["admin_note"] = body.note.strip()
    if existing:
        doc["created_at"] = existing.get("created_at") or now
    else:
        doc["created_at"] = now

    if hasattr(busy_col, "replace_one"):
        await busy_col.replace_one({"interval_id": interval_id}, doc, upsert=True)
    else:
        await busy_col.update_one({"interval_id": interval_id}, {"$set": doc}, upsert=True)

    enqueued = await enqueue_sync_conflicts_for_busy_intervals(db, busy_intervals=[doc])
    return doc, enqueued


@router.put("/resources/{resource_id}/busy-intervals/{interval_id}", response_model=dict)
async def upsert_manual_busy_interval(
    resource_id: str,
    interval_id: str,
    body: ManualBusyIntervalUpsert,
    ctx: dict = Depends(get_current_admin_or_practitioner),
    db=Depends(get_database),
):
    """
    Create or update an admin manual busy block on a resource.

    Flag off → 404. Overlapping confirmed app bookings → review_queue
    (sync_conflict), never silent cancel or payment rewrite (Q7).
    """
    _require_multi_resource_scheduling()

    resource = await db.resources.find_one({"resource_id": resource_id}, {"_id": 0})
    if not resource:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")

    if not body.date.strip() or not body.start_time.strip() or not body.end_time.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="date, start_time, and end_time are required",
        )

    saved, enqueued = await _upsert_manual_busy_interval(
        db,
        resource_id=resource_id,
        interval_id=interval_id,
        body=body,
    )
    return {
        "interval": saved,
        "sync_conflict_review_count": enqueued,
        "phase": "manual_busy",
    }


@router.post("/resources/{resource_id}/busy-intervals", response_model=dict)
async def create_manual_busy_interval(
    resource_id: str,
    body: ManualBusyIntervalUpsert,
    ctx: dict = Depends(get_current_admin_or_practitioner),
    db=Depends(get_database),
):
    """Create a manual busy interval (server-generated interval_id). Flag off → 404."""
    _require_multi_resource_scheduling()
    return await upsert_manual_busy_interval(
        resource_id=resource_id,
        interval_id=generate_id(),
        body=body,
        ctx=ctx,
        db=db,
    )


# ---- Section 3 — Outlook category maps --------------------------------------


def _outlook_connection_public(doc: dict) -> dict:
    """Safe summary for admin UI (no tokens)."""
    mailbox = doc.get("mailbox_email") or doc.get("microsoft_email")
    return {
        "connection_id": doc.get("connection_id"),
        "mailbox_email": mailbox,
        "microsoft_email": doc.get("microsoft_email"),
        "authoritative_for_resource_ids": doc.get("authoritative_for_resource_ids") or [],
        "visibility_only": bool(doc.get("visibility_only", False)),
        "last_sync_status": doc.get("last_sync_status"),
        "last_synced_at": doc.get("last_synced_at"),
        "last_sync_error": doc.get("last_sync_error"),
        "is_active": bool(doc.get("is_active", True)),
        "practitioner_id": doc.get("practitioner_id"),
        "category_map_count": len(doc.get("category_maps") or []),
    }


@router.get("/outlook/connections", response_model=dict)
async def list_outlook_connections(
    ctx: dict = Depends(get_current_admin_or_practitioner),
    db=Depends(get_database),
):
    """List Outlook mailbox connections for category-map picker (no secrets)."""
    _require_multi_resource_scheduling()
    rows = await db.outlook_calendar_connections.find({}, {"_id": 0}).to_list(200)
    items = [_outlook_connection_public(r) for r in rows]
    items.sort(
        key=lambda x: (
            str(x.get("mailbox_email") or x.get("connection_id") or "").lower()
        )
    )
    return {"items": items}


@router.get("/outlook/locked-connection-templates", response_model=dict)
async def get_locked_outlook_connection_templates(
    nichole_resource_id: str = Query(...),
    salt_resource_id: str = Query(...),
    ctx: dict = Depends(get_current_admin_or_practitioner),
):
    """
    Phase 0 locked mailbox + category map shapes (no DB read).

    Ops still must OAuth Clients@ separately; this is the target config after
    Nichole + Salt resource ids are known from seed.
    """
    _require_multi_resource_scheduling()
    return {
        "templates": build_locked_outlook_connection_templates(
            nichole_resource_id,
            salt_resource_id,
        ),
        "phase": "locked_defaults",
    }


@router.get("/outlook/connections/{connection_id}/category-maps", response_model=dict)
async def get_outlook_category_maps(
    connection_id: str,
    ctx: dict = Depends(get_current_admin_or_practitioner),
    db=Depends(get_database),
):
    _require_multi_resource_scheduling()
    conn = await db.outlook_calendar_connections.find_one(
        {"connection_id": connection_id}, {"_id": 0}
    )
    if not conn:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    maps = conn.get("category_maps") or []
    return {
        "connection_id": connection_id,
        "category_maps": maps,
        "authoritative_for_resource_ids": conn.get("authoritative_for_resource_ids") or [],
        "visibility_only": bool(conn.get("visibility_only", False)),
    }


@router.patch("/outlook/connections/{connection_id}", response_model=dict)
async def patch_outlook_connection_settings(
    connection_id: str,
    body: OutlookConnectionSettingsUpdate,
    ctx: dict = Depends(get_current_admin_or_practitioner),
    db=Depends(get_database),
):
    """Update safe Outlook connection metadata (no tokens). Flag off → 404."""
    _require_multi_resource_scheduling()
    conn = await db.outlook_calendar_connections.find_one(
        {"connection_id": connection_id}, {"_id": 0}
    )
    if not conn:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")

    fields_set = set(getattr(body, "model_fields_set", set()))
    if not fields_set:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields to update",
        )

    patch: dict[str, Any] = {}
    if "authoritative_for_resource_ids" in fields_set:
        ids = body.authoritative_for_resource_ids or []
        for rid in ids:
            resource = await db.resources.find_one({"resource_id": rid}, {"_id": 0})
            if not resource:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Unknown resource_id in authoritative_for_resource_ids: {rid}",
                )
        patch["authoritative_for_resource_ids"] = list(ids)
    if "visibility_only" in fields_set and body.visibility_only is not None:
        patch["visibility_only"] = bool(body.visibility_only)
    if "is_active" in fields_set and body.is_active is not None:
        patch["is_active"] = bool(body.is_active)
    if "mailbox_email" in fields_set:
        email = (body.mailbox_email or "").strip()
        patch["mailbox_email"] = email or None

    if not patch:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields to update",
        )

    patch["updated_at"] = _utc_now()
    await db.outlook_calendar_connections.update_one(
        {"connection_id": connection_id},
        {"$set": patch},
    )
    updated = await db.outlook_calendar_connections.find_one(
        {"connection_id": connection_id}, {"_id": 0}
    )
    return _outlook_connection_public(updated or {**conn, **patch})


@router.put("/outlook/connections/{connection_id}/category-maps", response_model=dict)
async def put_outlook_category_maps(
    connection_id: str,
    body: CategoryMapsPut,
    ctx: dict = Depends(get_current_admin_or_practitioner),
    db=Depends(get_database),
):
    _require_multi_resource_scheduling()
    conn = await db.outlook_calendar_connections.find_one(
        {"connection_id": connection_id}, {"_id": 0}
    )
    if not conn:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")

    maps = [m.model_dump() for m in body.category_maps]
    # Empty list is allowed (clears maps) — sync will fail-closed until remapped.
    await db.outlook_calendar_connections.update_one(
        {"connection_id": connection_id},
        {"$set": {"category_maps": maps, "updated_at": _utc_now()}},
    )
    return {
        "connection_id": connection_id,
        "category_maps": maps,
    }


# ---- Section 4 — Explain / preview + review queue (Phase 5) ------------------


async def _resource_sync_stale(db, resource_id: str) -> bool:
    """Fail-closed when any authoritative connection covering this resource is unhealthy."""
    connections_col = getattr(db, "outlook_calendar_connections", None)
    if connections_col is None:
        return False
    try:
        rows = await connections_col.find(
            {
                "$or": [
                    {"authoritative_for_resource_ids": resource_id},
                    {"category_maps.resource_ids": resource_id},
                ],
                "visibility_only": {"$ne": True},
            },
            {"_id": 0},
        ).to_list(50)
    except Exception:
        # Empty-DB / mock without find → treat as no sync dependency.
        return False
    if not rows:
        return False
    now = _utc_now()
    for conn in rows:
        if sync_is_stale(
            last_sync_status=conn.get("last_sync_status"),
            last_synced_at=conn.get("last_synced_at"),
            now=now,
            stale_after_minutes=SYNC_STALE_AFTER_MINUTES,
            outlook_required=True,
        ):
            return True
    return False


@router.get("/availability/explain", response_model=dict)
async def explain_availability(
    service_id: str = Query(...),
    date: str = Query(..., description="YYYY-MM-DD clinic-local"),
    start: Optional[str] = Query(
        None, description="Optional session start HH:MM clinic-local"
    ),
    resource_id: Optional[str] = Query(
        None, description="Override; defaults to service.required_resource_id"
    ),
    ctx: dict = Depends(get_current_admin_or_practitioner),
    db=Depends(get_database),
):
    """
    Structured “why unavailable” for admin preview (Phase 5).

    Flag off → 404. Flag on → pure explainer over service/resource/busy/sync.
    """
    _require_multi_resource_scheduling()

    service = await db.services.find_one({"service_id": service_id}, {"_id": 0})
    if not service:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")

    # When handlers are invoked directly in unit tests, unresolved Query() defaults
    # are objects — only treat real strings as overrides.
    rid = resource_id if isinstance(resource_id, str) and resource_id else None
    rid = rid or service.get("required_resource_id")
    if not rid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="service has no required_resource_id; pass resource_id",
        )

    resource = await db.resources.find_one({"resource_id": rid}, {"_id": 0})
    if not resource:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")

    start_hhmm = start if isinstance(start, str) and start else None

    busy: list = []
    busy_col = getattr(db, "resource_busy_intervals", None)
    if busy_col is not None:
        try:
            busy = await busy_col.find(
                {"resource_id": rid, "date": date},
                {"_id": 0},
            ).to_list(500)
        except Exception:
            busy = []

    stale = await _resource_sync_stale(db, rid)
    explained = explain_slot(
        date_str=date,
        service=service,
        resource=resource,
        busy_intervals=busy,
        start_time=start_hhmm,
        sync_stale=stale,
    )

    open_count = 0
    review_col = getattr(db, "review_queue", None)
    if review_col is not None:
        try:
            if hasattr(review_col, "count_documents"):
                open_count = int(
                    await review_col.count_documents({"status": "open"})
                )
            else:
                open_rows = await review_col.find(
                    {"status": "open"}, {"_id": 0}
                ).to_list(500)
                open_count = len(open_rows)
        except Exception:
            open_count = 0

    return {
        "service_id": service_id,
        "resource_id": rid,
        "date": date,
        "start": start_hhmm,
        "available": explained["available"],
        "reasons": explained["reasons"],
        "open_windows": explained.get("open_windows"),
        "free_intervals": explained.get("free_intervals"),
        "review_queue_open_count": open_count,
        "phase": "explain",
    }


@router.get("/review-queue", response_model=dict)
async def list_review_queue(
    status_filter: Optional[str] = Query("open", alias="status"),
    ctx: dict = Depends(get_current_admin_or_practitioner),
    db=Depends(get_database),
):
    """Review queue list (Phase 5). Resolve/dismiss when flag on."""
    _require_multi_resource_scheduling()
    review_col = getattr(db, "review_queue", None)
    if review_col is None:
        return {"items": [], "phase": "list"}

    query: dict[str, Any] = {}
    status_value = status_filter if isinstance(status_filter, str) else "open"
    if status_value:
        query["status"] = status_value
    try:
        rows = await review_col.find(query, {"_id": 0}).to_list(200)
    except Exception:
        rows = []
    return {"items": rows, "phase": "list"}


@router.post("/review-queue/{review_id}/resolve", response_model=dict)
async def resolve_review_queue_item(
    review_id: str,
    body: ReviewQueueResolveBody = ReviewQueueResolveBody(),
    ctx: dict = Depends(get_current_admin_or_practitioner),
    db=Depends(get_database),
):
    _require_multi_resource_scheduling()
    review_col = getattr(db, "review_queue", None)
    if review_col is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    row = await review_col.find_one({"review_id": review_id}, {"_id": 0})
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review item not found")
    if row.get("status") != "open":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Review item is not open",
        )
    now = _utc_now().isoformat()
    patch: dict[str, Any] = {
        "status": "resolved",
        "resolved_at": now,
    }
    if body.note:
        payload = dict(row.get("payload") or {})
        payload["resolve_note"] = body.note
        patch["payload"] = payload
    await review_col.update_one({"review_id": review_id}, {"$set": patch})
    updated = await review_col.find_one({"review_id": review_id}, {"_id": 0})
    return {"item": updated, "phase": "resolve"}


@router.post("/review-queue/{review_id}/dismiss", response_model=dict)
async def dismiss_review_queue_item(
    review_id: str,
    body: ReviewQueueDismissBody = ReviewQueueDismissBody(),
    ctx: dict = Depends(get_current_admin_or_practitioner),
    db=Depends(get_database),
):
    _require_multi_resource_scheduling()
    review_col = getattr(db, "review_queue", None)
    if review_col is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    row = await review_col.find_one({"review_id": review_id}, {"_id": 0})
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review item not found")
    if row.get("status") != "open":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Review item is not open",
        )
    now = _utc_now().isoformat()
    patch: dict[str, Any] = {
        "status": "dismissed",
        "resolved_at": now,
    }
    if body.reason:
        payload = dict(row.get("payload") or {})
        payload["dismiss_reason"] = body.reason
        patch["payload"] = payload
    await review_col.update_one({"review_id": review_id}, {"$set": patch})
    updated = await review_col.find_one({"review_id": review_id}, {"_id": 0})
    return {"item": updated, "phase": "dismiss"}

