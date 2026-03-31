"""
Authentication API Routes
"""
import secrets
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from application.dto import (
    RegisterRequest, LoginRequest, TokenResponse, RefreshTokenRequest,
    SendVerificationOtpRequest, VerifyEmailOtpRequest
)
from application.use_cases import AuthUseCase
from presentation.dependencies import get_auth_use_case, get_user_repo
from infrastructure.cache import get_cache_service
from infrastructure.repositories import MongoUserRepository
from infrastructure.external.email_service import get_email_service

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


@router.post("/send-verification-otp", response_model=dict)
async def send_verification_otp(
    request: SendVerificationOtpRequest,
    user_repo: MongoUserRepository = Depends(get_user_repo),
):
    """Send an email verification OTP code."""
    user = await user_repo.get_by_email(request.email)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    cache = await get_cache_service()
    otp_code = f"{secrets.randbelow(1000000):06d}"
    otp_key = f"auth:verify_email_otp:{request.email.lower()}"
    await cache.set(otp_key, {"code": otp_code}, ttl=600)

    email_service = get_email_service()
    result = await email_service.send_verification_otp(request.email, otp_code, expires_minutes=10)
    if not result.get("success"):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=result.get("message", "Email delivery failed"))

    return {"message": "Verification code sent", "provider": result.get("provider", "unknown")}


@router.post("/verify-email-otp", response_model=dict)
async def verify_email_otp(
    request: VerifyEmailOtpRequest,
    user_repo: MongoUserRepository = Depends(get_user_repo),
):
    """Verify email with OTP and mark user as verified."""
    cache = await get_cache_service()
    otp_key = f"auth:verify_email_otp:{request.email.lower()}"
    cached = await cache.get(otp_key)

    if not cached or str(cached.get("code")) != str(request.code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired verification code")

    user = await user_repo.get_by_email(request.email)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    await user_repo.update(
        user["user_id"],
        {"is_verified": True, "updated_at": datetime.now(timezone.utc).isoformat()},
    )
    await cache.delete(otp_key)

    return {"message": "Email verified successfully"}
