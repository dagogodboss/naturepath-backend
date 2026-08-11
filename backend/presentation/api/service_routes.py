"""
Services API Routes
"""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import Any, Dict, List, Optional

from application.dto import CreateServiceRequest, UpdateServiceRequest
from application.use_cases import BookingUseCase, ServiceUseCase
from infrastructure.repositories import MongoPractitionerRepository
from presentation.dependencies import (
    get_booking_use_case,
    get_current_admin,
    get_current_admin_or_practitioner,
    get_optional_user,
    get_practitioner_repo,
    get_service_use_case,
)
from core.rbac import Permission, has_permission
from application.service_policy import service_requires_discovery

router = APIRouter(prefix="/services", tags=["Services"])


async def _discovery_gate_active(
    optional_user: Optional[Dict[str, Any]],
    booking_use_case: BookingUseCase,
) -> bool:
    """
    True when non-discovery booking is locked for this caller.
    Unlock only when discovery state is completed (staff-marked).
    Staff with SERVICE_UPDATE bypass the lock.
    """
    if optional_user is not None and has_permission(optional_user, Permission.SERVICE_UPDATE):
        return False
    if optional_user is None:
        return True
    elig = await booking_use_case.get_discovery_eligibility(optional_user["user_id"])
    return elig.get("state") != "completed"

def _annotate_booking_lock(
    service: Dict[str, Any],
    gate_active: bool,
) -> Dict[str, Any]:
    """Marketing list shows all services; booking_locked gates non-discovery CTAs."""
    return {
        **service,
        "booking_locked": bool(gate_active and service_requires_discovery(service)),
    }


async def _annotate_services_for_caller(
    services: List[Dict[str, Any]],
    optional_user: Optional[Dict[str, Any]],
    booking_use_case: BookingUseCase,
) -> List[Dict[str, Any]]:
    gate_active = await _discovery_gate_active(optional_user, booking_use_case)
    return [_annotate_booking_lock(s, gate_active) for s in services]


@router.get("", response_model=List[dict])
async def get_all_services(
    category: Optional[str] = None,
    optional_user: Optional[dict] = Depends(get_optional_user),
    service_use_case: ServiceUseCase = Depends(get_service_use_case),
    booking_use_case: BookingUseCase = Depends(get_booking_use_case),
):
    """Full service catalog for marketing; non-discovery rows may be booking_locked."""
    if category:
        rows = await service_use_case.get_services_by_category(category)
    else:
        rows = await service_use_case.get_all_services()
    return await _annotate_services_for_caller(rows, optional_user, booking_use_case)


@router.get("/featured", response_model=List[dict])
async def get_featured_services(
    optional_user: Optional[dict] = Depends(get_optional_user),
    service_use_case: ServiceUseCase = Depends(get_service_use_case),
    booking_use_case: BookingUseCase = Depends(get_booking_use_case),
):
    """Featured services with the same lock annotation as the full list."""
    rows = await service_use_case.get_featured_services()
    return await _annotate_services_for_caller(rows, optional_user, booking_use_case)


@router.get("/{service_id}/reviews", response_model=List[dict])
async def get_service_reviews(
    service_id: str,
    service_use_case: ServiceUseCase = Depends(get_service_use_case),
):
    """Reviews for a service (catalog is publicly viewable)."""
    try:
        detail = await service_use_case.get_service_by_id(service_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return detail.get("reviews", [])


@router.get("/{service_id}", response_model=dict)
async def get_service(
    service_id: str,
    optional_user: Optional[dict] = Depends(get_optional_user),
    service_use_case: ServiceUseCase = Depends(get_service_use_case),
    booking_use_case: BookingUseCase = Depends(get_booking_use_case),
):
    """Get a specific service by ID (viewable by guests; booking_locked when gated)."""
    try:
        data = await service_use_case.get_service_by_id(service_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    gate_active = await _discovery_gate_active(optional_user, booking_use_case)
    return _annotate_booking_lock(data, gate_active)


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_service(
    request: CreateServiceRequest,
    ctx: dict = Depends(get_current_admin_or_practitioner),
    service_use_case: ServiceUseCase = Depends(get_service_use_case),
    practitioner_repo: MongoPractitionerRepository = Depends(get_practitioner_repo),
):
    """Create a new service (admin or practitioner). Practitioners get the service linked to their profile."""
    effective = request
    if not has_permission(ctx["user"], Permission.USER_ROLE_MANAGE):
        effective = request.model_copy(
            update={"is_featured": False, "revel_product_id": None, "is_discovery_entry": False}
        )
    is_discovery_entry = (
        bool(effective.is_discovery_entry)
        if has_permission(ctx["user"], Permission.USER_ROLE_MANAGE)
        else False
    )
    created = await service_use_case.create_service(
        name=effective.name,
        description=effective.description,
        category=effective.category,
        duration_minutes=effective.duration_minutes,
        price=effective.price,
        discount_price=effective.discount_price,
        image_url=effective.image_url,
        is_featured=effective.is_featured,
        max_capacity=effective.max_capacity,
        revel_product_id=effective.revel_product_id,
        benefits=effective.benefits,
        warning_copy=effective.warning_copy,
        is_discovery_entry=is_discovery_entry,
        requires_discovery=effective.requires_discovery,
    )
    if not has_permission(ctx["user"], Permission.USER_ROLE_MANAGE) and ctx.get("practitioner"):
        p = ctx["practitioner"]
        services = list(p.get("services", []))
        sid = created["service_id"]
        if sid not in services:
            services.append(sid)
            await practitioner_repo.update(p["practitioner_id"], {"services": services})
    return created


@router.patch("/{service_id}", response_model=dict)
async def update_service(
    service_id: str,
    request: UpdateServiceRequest,
    ctx: dict = Depends(get_current_admin_or_practitioner),
    service_use_case: ServiceUseCase = Depends(get_service_use_case),
):
    """Update a service (admin/owner or practitioner for their linked offerings)."""
    user = ctx["user"]
    practitioner = ctx.get("practitioner")
    updates = request.model_dump(exclude_unset=True, exclude_none=True)
    if not has_permission(user, Permission.USER_ROLE_MANAGE):
        if not practitioner:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Practitioner profile required to update services",
            )
        if service_id not in practitioner.get("services", []):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not allowed to update this service",
            )
        for k in ("is_featured", "revel_product_id", "is_discovery_entry", "requires_discovery"):
            updates.pop(k, None)
    if not updates:
        try:
            return await service_use_case.get_service_by_id(service_id)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    try:
        return await service_use_case.update_service(service_id, **updates)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.delete("/{service_id}")
async def delete_service(
    service_id: str,
    current_admin: dict = Depends(get_current_admin),
    service_use_case: ServiceUseCase = Depends(get_service_use_case)
):
    """Deactivate a service (Admin only)"""
    try:
        await service_use_case.delete_service(service_id)
        return {"success": True, "message": "Service deactivated"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/sync-revel")
async def sync_services_with_revel(
    current_admin: dict = Depends(get_current_admin),
    service_use_case: ServiceUseCase = Depends(get_service_use_case)
):
    """Sync services with REVEL POS (Admin only)"""
    return await service_use_case.sync_with_revel()
