"""
Services API Routes
"""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional
from application.dto import CreateServiceRequest, ServiceResponse, UpdateServiceRequest
from application.use_cases import ServiceUseCase
from presentation.dependencies import (
    get_service_use_case,
    get_current_admin
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
    current_admin: dict = Depends(get_current_admin),
    service_use_case: ServiceUseCase = Depends(get_service_use_case)
):
    """Create a new service (Admin only)"""
    return await service_use_case.create_service(
        name=request.name,
        description=request.description,
        category=request.category,
        duration_minutes=request.duration_minutes,
        price=request.price,
        discount_price=request.discount_price,
        image_url=request.image_url,
        is_featured=request.is_featured,
        max_capacity=request.max_capacity,
        revel_product_id=request.revel_product_id
    )


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
