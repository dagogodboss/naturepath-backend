"""
Admin API Routes - Dashboard and Analytics
"""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from datetime import datetime, timezone, timedelta
from application.dto import AdminStatsResponse, BookingAnalyticsResponse
from presentation.dependencies import (
    get_current_admin,
    get_user_repo,
    get_practitioner_repo,
    get_service_repo,
    get_booking_repo,
    get_payment_repo
)
from infrastructure.repositories import (
    MongoUserRepository,
    MongoPractitionerRepository,
    MongoServiceRepository,
    MongoBookingRepository,
    MongoPaymentRepository
)
from core.rbac import normalize_role
from .admin_rbac_routes import router as admin_rbac_router

router = APIRouter(prefix="/admin", tags=["Admin Dashboard"])
router.include_router(admin_rbac_router, prefix="/rbac", tags=["Admin RBAC"])


@router.get("/stats", response_model=dict)
async def get_admin_stats(
    current_admin: dict = Depends(get_current_admin),
    user_repo: MongoUserRepository = Depends(get_user_repo),
    practitioner_repo: MongoPractitionerRepository = Depends(get_practitioner_repo),
    service_repo: MongoServiceRepository = Depends(get_service_repo),
    booking_repo: MongoBookingRepository = Depends(get_booking_repo)
):
    """Get admin dashboard statistics"""
    # Get counts
    customers = await user_repo.get_by_role("customer")
    practitioners = await practitioner_repo.list_all()
    services = await service_repo.get_active()
    all_bookings = await booking_repo.list_all(limit=10000)
    
    # Calculate date ranges
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    week_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
    month_start = now.replace(day=1).strftime("%Y-%m-%d")
    
    # Filter bookings
    bookings_today = [b for b in all_bookings if b.get("slot", {}).get("date") == today]
    bookings_week = [
        b for b in all_bookings 
        if b.get("slot", {}).get("date", "") >= week_start
    ]
    bookings_month = [
        b for b in all_bookings 
        if b.get("slot", {}).get("date", "") >= month_start
    ]
    
    # Calculate revenue (only confirmed/completed bookings)
    def calc_revenue(bookings):
        return sum(
            b.get("total_price", 0) 
            for b in bookings 
            if b.get("status") in ["confirmed", "completed"]
        )
    
    return {
        "total_customers": len(customers),
        "total_practitioners": len(practitioners),
        "total_services": len(services),
        "total_bookings": len(all_bookings),
        "bookings_today": len(bookings_today),
        "bookings_this_week": len(bookings_week),
        "bookings_this_month": len(bookings_month),
        "revenue_today": calc_revenue(bookings_today),
        "revenue_this_week": calc_revenue(bookings_week),
        "revenue_this_month": calc_revenue(bookings_month)
    }


@router.get("/analytics/bookings", response_model=dict)
async def get_booking_analytics(
    period: str = "week",  # day, week, month
    current_admin: dict = Depends(get_current_admin),
    booking_repo: MongoBookingRepository = Depends(get_booking_repo),
    service_repo: MongoServiceRepository = Depends(get_service_repo),
    practitioner_repo: MongoPractitionerRepository = Depends(get_practitioner_repo)
):
    """Get booking analytics"""
    now = datetime.now(timezone.utc)
    
    # Determine date range
    if period == "day":
        start_date = now.strftime("%Y-%m-%d")
        end_date = start_date
    elif period == "week":
        start_date = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
        end_date = (now + timedelta(days=6-now.weekday())).strftime("%Y-%m-%d")
    else:  # month
        start_date = now.replace(day=1).strftime("%Y-%m-%d")
        # Last day of month
        next_month = now.replace(day=28) + timedelta(days=4)
        end_date = (next_month - timedelta(days=next_month.day)).strftime("%Y-%m-%d")
    
    bookings = await booking_repo.get_by_date_range(start_date, end_date)
    
    # Calculate metrics
    confirmed_bookings = [b for b in bookings if b.get("status") in ["confirmed", "completed"]]
    total_revenue = sum(b.get("total_price", 0) for b in confirmed_bookings)
    
    # Top services
    service_counts = {}
    for b in bookings:
        sid = b.get("service_id")
        if sid not in service_counts:
            service_counts[sid] = {"count": 0, "revenue": 0}
        service_counts[sid]["count"] += 1
        if b.get("status") in ["confirmed", "completed"]:
            service_counts[sid]["revenue"] += b.get("total_price", 0)
    
    top_services = []
    for sid, data in sorted(service_counts.items(), key=lambda x: x[1]["count"], reverse=True)[:5]:
        service = await service_repo.get_by_id(sid)
        if service:
            top_services.append({
                "service_id": sid,
                "name": service["name"],
                "count": data["count"],
                "revenue": data["revenue"]
            })
    
    # Top practitioners
    pract_counts = {}
    for b in bookings:
        pid = b.get("practitioner_id")
        if pid not in pract_counts:
            pract_counts[pid] = {"count": 0, "revenue": 0}
        pract_counts[pid]["count"] += 1
        if b.get("status") in ["confirmed", "completed"]:
            pract_counts[pid]["revenue"] += b.get("total_price", 0)
    
    top_practitioners = []
    for pid, data in sorted(pract_counts.items(), key=lambda x: x[1]["count"], reverse=True)[:5]:
        practitioner = await practitioner_repo.get_by_id(pid)
        if practitioner:
            top_practitioners.append({
                "practitioner_id": pid,
                "count": data["count"],
                "revenue": data["revenue"]
            })
    
    # Daily breakdown
    daily_data = {}
    for b in bookings:
        date = b.get("slot", {}).get("date", "unknown")
        if date not in daily_data:
            daily_data[date] = {"count": 0, "revenue": 0}
        daily_data[date]["count"] += 1
        if b.get("status") in ["confirmed", "completed"]:
            daily_data[date]["revenue"] += b.get("total_price", 0)
    
    booking_trends = [
        {"date": date, "count": data["count"], "revenue": data["revenue"]}
        for date, data in sorted(daily_data.items())
    ]
    
    return {
        "period": period,
        "start_date": start_date,
        "end_date": end_date,
        "total_bookings": len(bookings),
        "total_revenue": total_revenue,
        "average_booking_value": total_revenue / len(confirmed_bookings) if confirmed_bookings else 0,
        "top_services": top_services,
        "top_practitioners": top_practitioners,
        "booking_trends": booking_trends
    }


@router.get("/customers", response_model=List[dict])
async def get_all_customers(
    current_admin: dict = Depends(get_current_admin),
    user_repo: MongoUserRepository = Depends(get_user_repo)
):
    """Get all customers"""
    customers = await user_repo.get_by_role("customer")
    for c in customers:
        c.pop("password_hash", None)
    return customers


@router.get("/users", response_model=List[dict])
async def get_all_users(
    current_admin: dict = Depends(get_current_admin),
    user_repo: MongoUserRepository = Depends(get_user_repo)
):
    """Get all users"""
    users = await user_repo.list_all()
    for u in users:
        u.pop("password_hash", None)
    return users


@router.patch("/users/{user_id}/role")
async def update_user_role(
    user_id: str,
    role: str,
    current_admin: dict = Depends(get_current_admin),
    user_repo: MongoUserRepository = Depends(get_user_repo)
):
    """Update user role (Admin only)"""
    normalized = normalize_role(role)
    if normalized not in ["customer", "staff", "manager", "practitioner", "admin", "owner"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role")
    
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
    await user_repo.update(user_id, {"role": normalized})
    return {"success": True, "user_id": user_id, "new_role": normalized}


@router.patch("/users/{user_id}/status")
async def update_user_status(
    user_id: str,
    is_active: bool,
    current_admin: dict = Depends(get_current_admin),
    user_repo: MongoUserRepository = Depends(get_user_repo)
):
    """Activate/deactivate user (Admin only)"""
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
    await user_repo.update(user_id, {"is_active": is_active})
    return {"success": True, "user_id": user_id, "is_active": is_active}


@router.get("/analytics/store-funnel", response_model=dict)
async def get_store_funnel_analytics(
    days: int = 7,
    current_admin: dict = Depends(get_current_admin),
):
    """Store conversion funnel and payment method split for recent period."""
    if days < 1 or days > 90:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="days must be between 1 and 90")

    from infrastructure.database import get_database

    db = get_database()
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    query = {"created_at": {"$gte": start}}

    event_names = [
        "product_list_viewed",
        "add_to_cart",
        "checkout_started",
        "order_placed",
        "payment_success",
        "payment_failed",
        "checkout_failed",
    ]

    counts = {name: 0 for name in event_names}
    for name in event_names:
        counts[name] = await db.analytics_events.count_documents({**query, "event_name": name})

    payment_methods = {}
    async for row in db.analytics_events.aggregate(
        [
            {"$match": {**query, "event_name": {"$in": ["order_placed", "payment_success", "payment_failed"]}}},
            {
                "$project": {
                    "method": {"$ifNull": ["$metadata.paymentMethod", "unknown"]},
                    "event_name": 1,
                }
            },
            {
                "$group": {
                    "_id": {"method": "$method", "event": "$event_name"},
                    "count": {"$sum": 1},
                }
            },
        ]
    ):
        method = row["_id"]["method"]
        event = row["_id"]["event"]
        payment_methods.setdefault(method, {"order_placed": 0, "payment_success": 0, "payment_failed": 0})
        payment_methods[method][event] = row["count"]

    sessions = await db.analytics_events.distinct("session_id", query)
    unique_sessions = len([s for s in sessions if s])
    checkout_to_order_rate = (
        round((counts["order_placed"] / counts["checkout_started"]) * 100, 2)
        if counts["checkout_started"]
        else 0.0
    )
    payment_success_rate = (
        round((counts["payment_success"] / counts["order_placed"]) * 100, 2)
        if counts["order_placed"]
        else 0.0
    )

    return {
        "period_days": days,
        "unique_sessions": unique_sessions,
        "funnel": counts,
        "rates": {
            "checkout_to_order_pct": checkout_to_order_rate,
            "payment_success_pct": payment_success_rate,
        },
        "payment_method_split": payment_methods,
    }
