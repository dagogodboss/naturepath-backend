"""
Practitioners API Routes
"""
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse, RedirectResponse
from jose import JWTError, jwt
from typing import List, Optional
from application.access_control import (
    PractitionerAccessDenied,
    assert_admin_or_same_practitioner,
)
from application.dto import (
    CreatePractitionerRequest, PractitionerResponse, 
    UpdatePractitionerRequest, GenerateSlotsRequest
)
from application.use_cases import PractitionerUseCase
from presentation.dependencies import (
    get_practitioner_use_case,
    get_current_admin,
    get_current_practitioner,
    get_current_active_user,
    get_current_admin_or_practitioner,
)
from core.rbac import Permission, has_permission
from core.config import settings
from infrastructure.database import get_database
from infrastructure.external.microsoft_graph import OutlookTokenCipher
from application.outlook_sync import graph_client, sync_outlook_connection
from domain.entities import generate_id

router = APIRouter(prefix="/practitioners", tags=["Practitioners"])


def _outlook_configured() -> bool:
    return bool(
        settings.microsoft_client_id
        and settings.microsoft_client_secret
        and settings.microsoft_redirect_uri
    )


def _outlook_state(ctx: dict) -> str:
    practitioner = ctx.get("practitioner")
    if not practitioner:
        raise HTTPException(status_code=404, detail="Practitioner profile required")
    return jwt.encode(
        {
            "purpose": "outlook_connect",
            "sub": ctx["user"]["user_id"],
            "practitioner_id": practitioner["practitioner_id"],
            "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


@router.get("/outlook/status", response_model=dict)
async def outlook_status(
    ctx: dict = Depends(get_current_practitioner),
    db=Depends(get_database),
):
    practitioner = ctx.get("practitioner")
    connection = None
    if practitioner:
        connection = await db.outlook_calendar_connections.find_one(
            {"practitioner_id": practitioner["practitioner_id"]},
            {"_id": 0, "refresh_token_encrypted": 0, "subscription_client_state": 0},
        )
    return {"configured": _outlook_configured(), "connected": bool(connection), "connection": connection}


@router.post("/outlook/connect", response_model=dict)
async def connect_outlook(ctx: dict = Depends(get_current_practitioner)):
    if not _outlook_configured():
        raise HTTPException(status_code=503, detail="Outlook calendar is not configured")
    state_token = _outlook_state(ctx)
    return {"authorization_url": graph_client().authorization_url(state_token)}


@router.get("/outlook/callback")
async def outlook_callback(
    code: str,
    state_token: str = Query(alias="state"),
    db=Depends(get_database),
):
    try:
        claims = jwt.decode(
            state_token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        if claims.get("purpose") != "outlook_connect":
            raise JWTError("Wrong state purpose")
    except JWTError as exc:
        raise HTTPException(status_code=400, detail="Invalid or expired Outlook connection") from exc

    client = graph_client()
    token = await client.exchange_code(code)
    refresh_token = token.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=400, detail="Microsoft did not return offline calendar access")
    profile = await client.get_me(token["access_token"])
    connection_id = generate_id()
    existing = await db.outlook_calendar_connections.find_one(
        {"practitioner_id": claims["practitioner_id"]}, {"_id": 0}
    )
    if existing:
        connection_id = existing["connection_id"]
    now = datetime.now(timezone.utc).isoformat()
    connection = {
        "connection_id": connection_id,
        "practitioner_id": claims["practitioner_id"],
        "user_id": claims["sub"],
        "microsoft_user_id": profile.get("id"),
        "microsoft_email": profile.get("mail") or profile.get("userPrincipalName"),
        "refresh_token_encrypted": OutlookTokenCipher(settings.jwt_secret_key).encrypt(refresh_token),
        "is_active": True,
        "updated_at": now,
    }
    await db.outlook_calendar_connections.update_one(
        {"connection_id": connection_id},
        {"$set": connection, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )

    if settings.microsoft_graph_webhook_url:
        client_state = secrets.token_urlsafe(32)
        try:
            subscription = await client.create_subscription(
                token["access_token"],
                notification_url=settings.microsoft_graph_webhook_url,
                expiration=datetime.now(timezone.utc) + timedelta(days=3),
                client_state=client_state,
            )
            await db.outlook_calendar_connections.update_one(
                {"connection_id": connection_id},
                {"$set": {
                    "subscription_id": subscription.get("id"),
                    "subscription_expires_at": subscription.get("expirationDateTime"),
                    "subscription_client_state": client_state,
                }},
            )
        except Exception as exc:
            await db.outlook_calendar_connections.update_one(
                {"connection_id": connection_id},
                {"$set": {"subscription_error": str(exc)}},
            )

    from workers.outlook_calendar_worker import sync_outlook_connection_task
    sync_outlook_connection_task.delay(connection_id)
    target = f"{settings.public_app_url.rstrip('/')}/practitioner/availability?outlook=connected"
    return RedirectResponse(target, status_code=302)


@router.post("/outlook/sync", response_model=dict)
async def sync_outlook_now(
    ctx: dict = Depends(get_current_practitioner),
    db=Depends(get_database),
):
    practitioner = ctx.get("practitioner")
    if not practitioner:
        raise HTTPException(status_code=404, detail="Practitioner profile required")
    connection = await db.outlook_calendar_connections.find_one(
        {"practitioner_id": practitioner["practitioner_id"], "is_active": True}, {"_id": 0}
    )
    if not connection:
        raise HTTPException(status_code=404, detail="Outlook calendar is not connected")
    return await sync_outlook_connection(db, connection)


@router.get("/outlook/events", response_model=dict)
async def list_outlook_events(
    start_date: str,
    end_date: str,
    ctx: dict = Depends(get_current_practitioner),
    db=Depends(get_database),
):
    practitioner = ctx.get("practitioner")
    if not practitioner:
        raise HTTPException(status_code=404, detail="Practitioner profile required")
    rows = await db.outlook_calendar_events.find(
        {
            "practitioner_id": practitioner["practitioner_id"],
            "date": {"$gte": start_date, "$lte": end_date},
            "is_cancelled": {"$ne": True},
            "show_as": {"$ne": "free"},
        },
        {"_id": 0},
    ).sort([("date", 1), ("start_time", 1)]).to_list(length=1000)
    return {"items": rows, "total": len(rows)}


@router.delete("/outlook/disconnect", response_model=dict)
async def disconnect_outlook(
    ctx: dict = Depends(get_current_practitioner),
    db=Depends(get_database),
):
    practitioner = ctx.get("practitioner")
    if not practitioner:
        raise HTTPException(status_code=404, detail="Practitioner profile required")
    connection = await db.outlook_calendar_connections.find_one(
        {"practitioner_id": practitioner["practitioner_id"]}, {"_id": 0}
    )
    if connection:
        await db.outlook_calendar_events.delete_many({"connection_id": connection["connection_id"]})
        await db.outlook_calendar_connections.delete_one({"connection_id": connection["connection_id"]})
    return {"disconnected": True}


@router.post("/outlook/webhook")
async def outlook_webhook(
    request: Request,
    validation_token: Optional[str] = Query(default=None, alias="validationToken"),
    db=Depends(get_database),
):
    if validation_token:
        return PlainTextResponse(validation_token)
    payload = await request.json()
    accepted = 0
    from workers.outlook_calendar_worker import sync_outlook_connection_task
    for notice in payload.get("value") or []:
        connection = await db.outlook_calendar_connections.find_one(
            {
                "subscription_id": notice.get("subscriptionId"),
                "subscription_client_state": notice.get("clientState"),
                "is_active": True,
            },
            {"_id": 0},
        )
        if connection:
            sync_outlook_connection_task.delay(connection["connection_id"])
            accepted += 1
    return {"accepted": accepted}


@router.get("", response_model=List[dict])
async def get_all_practitioners(
    practitioner_use_case: PractitionerUseCase = Depends(get_practitioner_use_case)
):
    """Get all practitioners"""
    return await practitioner_use_case.get_all_practitioners()


@router.get("/featured", response_model=List[dict])
async def get_featured_practitioners(
    practitioner_use_case: PractitionerUseCase = Depends(get_practitioner_use_case)
):
    """Get featured practitioners for homepage"""
    return await practitioner_use_case.get_featured_practitioners()


@router.get("/by-service/{service_id}", response_model=List[dict])
async def get_practitioners_by_service(
    service_id: str,
    practitioner_use_case: PractitionerUseCase = Depends(get_practitioner_use_case)
):
    """Get practitioners that offer a specific service"""
    return await practitioner_use_case.get_practitioners_by_service(service_id)


@router.get("/{practitioner_id}", response_model=dict)
async def get_practitioner(
    practitioner_id: str,
    practitioner_use_case: PractitionerUseCase = Depends(get_practitioner_use_case)
):
    """Get a specific practitioner by ID"""
    try:
        return await practitioner_use_case.get_practitioner_by_id(practitioner_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("/{practitioner_id}/availability", response_model=List[dict])
async def get_practitioner_availability(
    practitioner_id: str,
    date: str,
    practitioner_use_case: PractitionerUseCase = Depends(get_practitioner_use_case)
):
    """Get available time slots for a practitioner on a specific date"""
    try:
        return await practitioner_use_case.get_availability(practitioner_id, date)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_practitioner(
    request: CreatePractitionerRequest,
    current_admin: dict = Depends(get_current_admin),
    practitioner_use_case: PractitionerUseCase = Depends(get_practitioner_use_case)
):
    """Create a new practitioner profile (Admin only)"""
    try:
        return await practitioner_use_case.create_practitioner(
            user_id=request.user_id,
            bio=request.bio,
            philosophy=request.philosophy,
            specialties=[s.model_dump() for s in request.specialties],
            certifications=request.certifications,
            services=request.services,
            availability=[a.model_dump() for a in request.availability],
            hourly_rate=request.hourly_rate,
            is_featured=request.is_featured
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch("/{practitioner_id}", response_model=dict)
async def update_practitioner(
    practitioner_id: str,
    request: UpdatePractitionerRequest,
    current_practitioner: dict = Depends(get_current_practitioner),
    practitioner_use_case: PractitionerUseCase = Depends(get_practitioner_use_case)
):
    """Update a practitioner profile"""
    # Check authorization
    practitioner = current_practitioner.get("practitioner")
    user = current_practitioner.get("user")
    
    if not has_permission(user, Permission.USER_ROLE_MANAGE):
        if not practitioner or practitioner["practitioner_id"] != practitioner_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only update your own profile"
            )
    
    try:
        updates = request.model_dump(exclude_unset=True, exclude_none=True)
        return await practitioner_use_case.update_practitioner(practitioner_id, **updates)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/{practitioner_id}/generate-slots", response_model=dict)
async def generate_availability_slots(
    practitioner_id: str,
    request: GenerateSlotsRequest,
    ctx: dict = Depends(get_current_admin_or_practitioner),
    practitioner_use_case: PractitionerUseCase = Depends(get_practitioner_use_case)
):
    """Generate availability slots (admin any practitioner; practitioner only self)."""
    acting_pid = (
        ctx["practitioner"]["practitioner_id"] if ctx.get("practitioner") else None
    )
    try:
        assert_admin_or_same_practitioner(
            ctx["user"].get("role") or "",
            acting_pid,
            practitioner_id,
        )
    except PractitionerAccessDenied as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    if request.practitioner_id is not None and request.practitioner_id != practitioner_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="practitioner_id in body must match the URL path when provided",
        )
    try:
        return await practitioner_use_case.generate_availability_slots(
            practitioner_id=practitioner_id,
            start_date=request.start_date,
            end_date=request.end_date
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
