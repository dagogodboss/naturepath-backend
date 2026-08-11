"""
Practitioner / ops client directory (customers who have booked with this practitioner).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from infrastructure.database import get_database
from presentation.dependencies import get_current_practitioner
from application.client_directory import client_booking_filter

router = APIRouter(prefix="/clients", tags=["Clients"])


async def _load_users_by_ids(db, user_ids: List[str], chunk_size: int = 500) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not user_ids:
        return out
    for i in range(0, len(user_ids), chunk_size):
        chunk = user_ids[i : i + chunk_size]
        rows = await db.users.find({"user_id": {"$in": chunk}}, {"_id": 0}).to_list(length=chunk_size)
        out.extend(rows)
    return out


@router.get("")
async def list_clients(
    q: Optional[str] = Query(default=None, description="Filter by name or email"),
    ctx: dict = Depends(get_current_practitioner),
    db=Depends(get_database),
):
    """Booked customers: clinic-wide for owners/admins, assigned-only for practitioners."""
    try:
        booking_query = client_booking_filter(ctx)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    stats: Dict[str, Dict[str, Any]] = {}
    booking_rows = (
        await db.bookings.find(
            booking_query,
            {"_id": 0, "customer_id": 1, "slot": 1},
        )
        .to_list(length=10000)
    )
    for b in booking_rows:
        cid = b.get("customer_id")
        if not cid:
            continue
        if cid not in stats:
            stats[cid] = {"total_sessions": 0, "last_visit_date": ""}
        stats[cid]["total_sessions"] += 1
        slot_date = (b.get("slot") or {}).get("date") or ""
        if slot_date > stats[cid]["last_visit_date"]:
            stats[cid]["last_visit_date"] = slot_date

    if not stats:
        return {"items": [], "total": 0}

    user_ids = list(stats.keys())
    users = await _load_users_by_ids(db, user_ids)

    items: List[Dict[str, Any]] = []
    qn = (q or "").strip().lower()
    for u in users:
        name = f"{u.get('first_name') or ''} {u.get('last_name') or ''}".strip()
        email = (u.get("email") or "").lower()
        if qn and qn not in name.lower() and qn not in email:
            continue
        cid = u["user_id"]
        st = stats.get(cid, {})
        items.append(
            {
                "client_id": cid,
                "name": name or email or cid,
                "email": u.get("email"),
                "phone": u.get("phone"),
                "total_sessions": st.get("total_sessions", 0),
                "last_visit_date": st.get("last_visit_date") or None,
            }
        )

    items.sort(key=lambda x: x.get("last_visit_date") or "", reverse=True)
    return {"items": items, "total": len(items)}


@router.get("/{client_id}")
async def get_client_detail(
    client_id: str,
    ctx: dict = Depends(get_current_practitioner),
    db=Depends(get_database),
):
    """Profile plus recent bookings for a client tied to this practitioner."""
    try:
        booking_query = client_booking_filter(ctx)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    has_booking = await db.bookings.count_documents(
        {**booking_query, "customer_id": client_id},
        limit=1,
    )
    if not has_booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    user = await db.users.find_one({"user_id": client_id}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    email = user.get("email")
    name = f"{user.get('first_name') or ''} {user.get('last_name') or ''}".strip()
    bookings = (
        await db.bookings.find(
            {**booking_query, "customer_id": client_id},
            {"_id": 0},
        )
        .sort("created_at", -1)
        .limit(50)
        .to_list(length=50)
    )

    service_ids = list(
        {
            b.get("service_id")
            for b in bookings
            if b.get("service_id")
        }
    )
    services = (
        await db.services.find(
            {"service_id": {"$in": service_ids}},
            {"_id": 0, "service_id": 1, "name": 1},
        ).to_list(length=max(len(service_ids), 1))
        if service_ids
        else []
    )
    service_names = {s.get("service_id"): s.get("name") for s in services}

    enriched: List[Dict[str, Any]] = []
    for b in bookings:
        slot = b.get("slot") or {}
        enriched.append(
            {
                "booking_id": b.get("booking_id"),
                "status": b.get("status"),
                "service_name": service_names.get(b.get("service_id")) or "Service",
                "date": slot.get("date"),
                "start_time": slot.get("start_time"),
                "end_time": slot.get("end_time"),
            }
        )

    # Deliberately omitted for practitioner scope: store order history is not guaranteed
    # to be tied to this practitioner relationship and can leak unrelated commerce data.
    store_orders: List[Dict[str, Any]] = []

    return {
        "client_id": client_id,
        "name": name or email or client_id,
        "email": user.get("email"),
        "phone": user.get("phone"),
        "join_date": user.get("created_at"),
        "appointments": enriched,
        "store_orders": store_orders,
    }
