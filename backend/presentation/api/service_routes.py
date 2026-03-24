"""
Services API Routes
"""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional
from application.dto import CreateServiceRequest, ServiceResponse, UpdateServiceRequest
from application.use_cases import ServiceUseCase
from infrastructure.repositories import MongoPractitionerRepository
from presentation.dependencies import (
    get_service_use_case,
    get_current_admin,
    get_current_admin_or_practitioner,
    get_practitioner_repo,
)

router = APIRouter(prefix="/services", tags=["Services"])


@router.get("", response_model=List[dict])
async def get_all_services(
    category: Optional[str] = None,
    service_use_case: ServiceUseCase = Depends(get_service_use_case)
):
    """Get all active services"""
    if category:
        return await service_use_case.get_services_by_category(category)
    return await service_use_case.get_all_services()


@router.get("/featured", response_model=List[dict])
async def get_featured_services(
    service_use_case: ServiceUseCase = Depends(get_service_use_case)
):
    """Get featured services for homepage"""
    return await service_use_case.get_featured_services()


@router.get("/{service_id}", response_model=dict)
async def get_service(
    service_id: str,
    service_use_case: ServiceUseCase = Depends(get_service_use_case)
):
    """Get a specific service by ID"""
    try:
        return await service_use_case.get_service_by_id(service_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_service(
    request: CreateServiceRequest,
    ctx: dict = Depends(get_current_admin_or_practitioner),
    service_use_case: ServiceUseCase = Depends(get_service_use_case),
    practitioner_repo: MongoPractitionerRepository = Depends(get_practitioner_repo),
):
    """Create a new service (admin or practitioner). Practitioners get the service linked to their profile."""
    effective = request
    if ctx["user"].get("role") == "practitioner":
        effective = request.model_copy(
            update={"is_featured": False, "revel_product_id": None}
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
        revel_product_id=effective.revel_product_id
    )
    if ctx["user"].get("role") == "practitioner" and ctx.get("practitioner"):
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
    current_admin: dict = Depends(get_current_admin),
    service_use_case: ServiceUseCase = Depends(get_service_use_case)
):
    """Update a service (Admin only)"""
    try:
        updates = request.model_dump(exclude_unset=True, exclude_none=True)
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
