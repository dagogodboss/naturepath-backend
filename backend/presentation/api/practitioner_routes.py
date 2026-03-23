"""
Practitioners API Routes
"""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional
from application.dto import (
    CreatePractitionerRequest, PractitionerResponse, 
    UpdatePractitionerRequest, GenerateSlotsRequest
)
from application.use_cases import PractitionerUseCase
from presentation.dependencies import (
    get_practitioner_use_case,
    get_current_admin,
    get_current_practitioner,
    get_current_active_user
)

router = APIRouter(prefix="/practitioners", tags=["Practitioners"])


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
    
    if user.get("role") != "admin":
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
    current_admin: dict = Depends(get_current_admin),
    practitioner_use_case: PractitionerUseCase = Depends(get_practitioner_use_case)
):
    """Generate availability slots for a practitioner (Admin only)"""
    try:
        return await practitioner_use_case.generate_availability_slots(
            practitioner_id=practitioner_id,
            start_date=request.start_date,
            end_date=request.end_date
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
