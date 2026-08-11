"""
Authentication API Routes
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from application.dto import (
    RegisterRequest, LoginRequest, TokenResponse, RefreshTokenRequest,
    GoogleOAuthRequest, CompleteOAuthPhoneRequest,
    SendVerificationOtpRequest, VerifyEmailOtpRequest,
    LookupEmailRequest, LookupEmailResponse,
)
from application.use_cases import AuthUseCase
from presentation.dependencies import get_auth_use_case, get_user_repo
from infrastructure.cache import get_cache_service
from infrastructure.repositories import MongoUserRepository
from infrastructure.external.email_service import get_email_service
from infrastructure.database import get_database
from application.email_verification import EmailVerificationStore, normalize_email
from core.config import settings

router = APIRouter(prefix="/auth", tags=["Authentication"])

LOOKUP_EMAIL_RATE_LIMIT = 10  # requests
LOOKUP_EMAIL_RATE_WINDOW_SEC = 60
OTP_SEND_RATE_LIMIT = 5  # requests
OTP_SEND_RATE_WINDOW_SEC = 60


def _client_mode_standalone(request: Request, body_mode: Optional[str] = None) -> bool:
    header = (request.headers.get("X-Client-Mode") or "").strip().lower()
    mode = (body_mode or "").strip().lower()
    return header == "standalone" or mode == "standalone"


@router.post("/register", response_model=dict, status_code=status.HTTP_201_CREATED)
async def register(
    request: RegisterRequest,
    auth_use_case: AuthUseCase = Depends(get_auth_use_case)
):
    """Register a new user account (or claim an unclaimed guest account)."""
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


@router.post("/oauth/google", response_model=dict)
async def oauth_google(
    body: GoogleOAuthRequest,
    http_request: Request,
    auth_use_case: AuthUseCase = Depends(get_auth_use_case),
):
    """
    Exchange a Google Identity Services / Firebase ID token for app JWTs.
    When phone is missing, returns needs_phone + setup_token (no access/refresh).
    Disabled when GOOGLE_OAUTH_CLIENT_ID is unset.
    """
    if not (settings.google_oauth_client_id or "").strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth is not configured",
        )
    try:
        return await auth_use_case.oauth_google(
            id_token=body.id_token,
            phone=body.phone,
            standalone=_client_mode_standalone(http_request),
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/oauth/complete-phone", response_model=dict)
async def oauth_complete_phone(
    body: CompleteOAuthPhoneRequest,
    http_request: Request,
    auth_use_case: AuthUseCase = Depends(get_auth_use_case),
):
    """Exchange phone_setup token + phone for full access/refresh JWTs."""
    try:
        return await auth_use_case.complete_oauth_phone(
            setup_token=body.setup_token,
            phone=body.phone,
            standalone=_client_mode_standalone(http_request),
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/oauth/google/status", response_model=dict)
async def oauth_google_status():
    """Frontend gate: whether Continue with Google is available."""
    enabled = bool((settings.google_oauth_client_id or "").strip())
    return {
        "enabled": enabled,
        "client_id": settings.google_oauth_client_id if enabled else None,
    }


@router.post("/lookup-email", response_model=LookupEmailResponse)
async def lookup_email(
    body: LookupEmailRequest,
    http_request: Request,
    auth_use_case: AuthUseCase = Depends(get_auth_use_case),
):
    """
    Minimal email recognition for checkout UX.
    Rate-limited; returns only { exists, needs_password } — no PII.
    """
    cache = await get_cache_service()
    client_host = http_request.client.host if http_request.client else "unknown"
    # Also key by email prefix to slow enumeration of many addresses from one IP.
    rate_key = f"auth:lookup_email:{client_host}"
    count = await cache.incr(rate_key, ttl=LOOKUP_EMAIL_RATE_WINDOW_SEC)
    if count > LOOKUP_EMAIL_RATE_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please try again shortly.",
        )
    return await auth_use_case.lookup_email(str(body.email))


@router.post("/refresh", response_model=dict)
async def refresh_token(
    request: RefreshTokenRequest,
    http_request: Request,
    auth_use_case: AuthUseCase = Depends(get_auth_use_case)
):
    """Refresh access token"""
    try:
        result = await auth_use_case.refresh_token(
            request.refresh_token,
            standalone=_client_mode_standalone(http_request, request.client_mode),
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))


@router.post("/send-verification-otp", response_model=dict)
async def send_verification_otp(
    request: SendVerificationOtpRequest,
    http_request: Request,
    user_repo: MongoUserRepository = Depends(get_user_repo),
    db=Depends(get_database),
):
    """Send an email verification OTP code.

    Always returns the same message whether or not the account exists, to avoid
    account enumeration. Delivery failures for known accounts still surface 503.
    """
    cache = await get_cache_service()
    client_host = http_request.client.host if http_request.client else "unknown"
    rate_key = f"auth:send_otp:{client_host}"
    count = await cache.incr(rate_key, ttl=OTP_SEND_RATE_WINDOW_SEC)
    if count > OTP_SEND_RATE_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please try again shortly.",
        )

    generic = {"message": "If an account exists for that email, a verification code has been sent"}
    user = await user_repo.get_by_email(request.email)
    if not user:
        return generic

    otp_code = f"{secrets.randbelow(1000000):06d}"
    normalized_email = normalize_email(request.email)
    challenge_store = EmailVerificationStore(
        db.email_verification_challenges,
        secret=settings.jwt_secret_key,
    )
    try:
        await challenge_store.issue(normalized_email, otp_code)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Verification is temporarily unavailable. Please try again.",
        )

    email_service = get_email_service()
    result = await email_service.send_verification_otp(normalized_email, otp_code, expires_minutes=10)
    if not result.get("success"):
        await challenge_store.revoke(normalized_email)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=result.get("message", "Email delivery failed"))

    return generic


@router.post("/verify-email-otp", response_model=dict)
async def verify_email_otp(
    request: VerifyEmailOtpRequest,
    user_repo: MongoUserRepository = Depends(get_user_repo),
    db=Depends(get_database),
):
    """Verify email with OTP and mark user as verified."""
    normalized_email = normalize_email(request.email)
    challenge_store = EmailVerificationStore(
        db.email_verification_challenges,
        secret=settings.jwt_secret_key,
    )
    if not await challenge_store.consume(normalized_email, str(request.code)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired verification code")

    user = await user_repo.get_by_email(normalized_email)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    await user_repo.update(
        user["user_id"],
        {"is_verified": True, "updated_at": datetime.now(timezone.utc).isoformat()},
    )
    # Allow password claim of unclaimed guest accounts within the claim window.
    from application.use_cases.auth_use_case import (
        EMAIL_CLAIM_OK_TTL_SEC,
        email_claim_ok_key,
    )

    cache = await get_cache_service()
    await cache.set(
        email_claim_ok_key(normalized_email),
        {"verified": True},
        ttl=EMAIL_CLAIM_OK_TTL_SEC,
    )

    return {"message": "Email verified successfully"}
