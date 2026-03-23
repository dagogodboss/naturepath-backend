"""
Authentication API Routes
"""
from fastapi import APIRouter, Depends, HTTPException, status
from application.dto import (
    RegisterRequest, LoginRequest, TokenResponse, RefreshTokenRequest
)
from application.use_cases import AuthUseCase
from presentation.dependencies import get_auth_use_case

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=dict, status_code=status.HTTP_201_CREATED)
async def register(
    request: RegisterRequest,
    auth_use_case: AuthUseCase = Depends(get_auth_use_case)
):
    """Register a new user account"""
    try:
        result = await auth_use_case.register(
            email=request.email,
            password=request.password,
            first_name=request.first_name,
            last_name=request.last_name,
            phone=request.phone
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/login", response_model=dict)
async def login(
    request: LoginRequest,
    auth_use_case: AuthUseCase = Depends(get_auth_use_case)
):
    """Login with email and password"""
    try:
        result = await auth_use_case.login(
            email=request.email,
            password=request.password
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))


@router.post("/refresh", response_model=dict)
async def refresh_token(
    request: RefreshTokenRequest,
    auth_use_case: AuthUseCase = Depends(get_auth_use_case)
):
    """Refresh access token"""
    try:
        result = await auth_use_case.refresh_token(request.refresh_token)
        return result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
