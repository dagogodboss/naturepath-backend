"""
Authentication Use Cases - Application Layer
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from passlib.context import CryptContext
from jose import jwt, JWTError
from core.config import settings
from core.rbac import normalize_role
from domain.entities import User, UserRole, generate_id, utc_now
from infrastructure.repositories import MongoUserRepository
from workers.notification_worker import send_welcome_email

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Short-lived proof that the email owner completed OTP before claiming a guest account.
# Set by /auth/verify-email-otp; consumed by register claim path.
EMAIL_CLAIM_OK_PREFIX = "auth:claim_ok:"
EMAIL_CLAIM_OK_TTL_SEC = 1800


def email_claim_ok_key(email: str) -> str:
    return f"{EMAIL_CLAIM_OK_PREFIX}{(email or '').strip().lower()}"


def _is_unclaimed_account(user: Dict[str, Any]) -> bool:
    """
    Guest-purchase accounts awaiting claim only.

    Never treat oauth / password accounts as unclaimed — missing password_hash
    is normal for Google OAuth and must not enable takeover via guest upsert
    or register claim.
    """
    if user.get("auth_method") == "oauth":
        return False
    if user.get("account_claimed") is True:
        return False
    if user.get("account_claimed") is False:
        return True
    if user.get("auth_method") == "guest_purchase":
        return True
    return False


class AuthUseCase:
    """Authentication use cases"""
    
    def __init__(self, user_repo: MongoUserRepository):
        self.user_repo = user_repo

    async def _consume_email_claim_proof(self, email: str) -> bool:
        """Return True and delete claim proof if OTP verification marked this email."""
        from infrastructure.cache import get_cache_service

        cache = await get_cache_service()
        key = email_claim_ok_key(email)
        proof = await cache.get(key)
        if not proof:
            return False
        await cache.delete(key)
        return True
    
    def _hash_password(self, password: str) -> str:
        return pwd_context.hash(password)
    
    def _verify_password(self, plain_password: str, hashed_password: str) -> bool:
        return pwd_context.verify(plain_password, hashed_password)
    
    def _create_access_token(self, data: dict, expires_delta: Optional[timedelta] = None) -> str:
        to_encode = data.copy()
        expire = datetime.now(timezone.utc) + (
            expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
        )
        to_encode.update({"exp": expire, "type": "access"})
        return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    
    def _create_refresh_token(
        self, data: dict, *, standalone: bool = False
    ) -> str:
        to_encode = data.copy()
        days = (
            settings.refresh_token_expire_days_standalone
            if standalone
            else settings.refresh_token_expire_days
        )
        expire = datetime.now(timezone.utc) + timedelta(days=days)
        to_encode.update({"exp": expire, "type": "refresh"})
        if standalone:
            to_encode["standalone"] = True
        return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

    def _user_public(self, user: Dict[str, Any]) -> Dict[str, Any]:
        role = normalize_role(user.get("role"))
        return {
            "user_id": user["user_id"],
            "email": user["email"],
            "first_name": user.get("first_name"),
            "last_name": user.get("last_name"),
            "phone": user.get("phone"),
            "role": role,
        }

    @staticmethod
    def _phone_missing(user: Dict[str, Any]) -> bool:
        return len((user.get("phone") or "").strip()) < 7

    def _create_phone_setup_token(self, user: Dict[str, Any]) -> str:
        """Short-lived token that only authorizes completing the phone step."""
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
        return jwt.encode(
            {
                "sub": user["user_id"],
                "email": user["email"],
                "exp": expire,
                "type": "phone_setup",
            },
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )

    def _token_payload_for_user(
        self, user: Dict[str, Any], *, standalone: bool = False
    ) -> Dict[str, Any]:
        role = normalize_role(user.get("role"))
        return {
            "access_token": self._create_access_token(
                {"sub": user["user_id"], "email": user["email"], "role": role}
            ),
            "refresh_token": self._create_refresh_token(
                {"sub": user["user_id"], "email": user["email"], "role": role},
                standalone=standalone,
            ),
            "token_type": "bearer",
            "expires_in": settings.access_token_expire_minutes * 60,
            "needs_phone": False,
            "user": self._user_public(user),
        }

    def _phone_setup_payload(self, user: Dict[str, Any]) -> Dict[str, Any]:
        """OAuth succeeded but phone is required before issuing app JWTs."""
        return {
            "needs_phone": True,
            "setup_token": self._create_phone_setup_token(user),
            "setup_token_expires_in": 900,
            "user": self._user_public(user),
        }
    
    async def register(
        self,
        email: str,
        password: str,
        first_name: str,
        last_name: str,
        phone: Optional[str] = None,
        role: UserRole = UserRole.CUSTOMER
    ) -> Dict[str, Any]:
        """Register a new user, or claim an unclaimed guest-purchase account."""
        email_norm = (email or "").strip().lower()
        phone_norm = (phone or "").strip()
        canonical_role = UserRole(normalize_role(role.value))

        if canonical_role == UserRole.CUSTOMER and len(phone_norm) < 7:
            raise ValueError("Phone number is required")

        existing = await self.user_repo.get_by_email(email_norm)
        if existing:
            existing_role = normalize_role(existing.get("role"))
            if _is_unclaimed_account(existing) and existing_role == "customer":
                # Require prior email OTP verification (see /auth/verify-email-otp).
                # Prevents takeover of guest-purchase accounts by password alone.
                if not await self._consume_email_claim_proof(email_norm):
                    raise ValueError(
                        "Verify your email before claiming this account. "
                        "Request a code via /api/auth/send-verification-otp, "
                        "then /api/auth/verify-email-otp."
                    )
                updated = await self.user_repo.update(
                    existing["user_id"],
                    {
                        "password_hash": self._hash_password(password),
                        "first_name": first_name,
                        "last_name": last_name,
                        "phone": phone_norm,
                        "auth_method": "password",
                        "account_claimed": True,
                        "is_verified": True,
                        "email": email_norm,
                    },
                )
                logger.info(f"Guest account claimed via register: {email_norm}")
                try:
                    send_welcome_email.delay(email_norm, f"{first_name} {last_name}")
                except Exception as e:
                    logger.warning(f"Failed to queue welcome email: {e}")
                return self._token_payload_for_user(updated or existing)
            raise ValueError("User with this email already exists")
        
        # Create user
        user = User(
            user_id=generate_id(),
            email=email_norm,
            password_hash=self._hash_password(password),
            first_name=first_name,
            last_name=last_name,
            phone=phone_norm,
            role=canonical_role,
            is_active=True,
            is_verified=False,
            is_discovery_completed=False,
            auth_method="password",
            account_claimed=True,
        )
        
        user_dict = user.model_dump()
        user_dict["created_at"] = user_dict["created_at"].isoformat()
        user_dict["updated_at"] = user_dict["updated_at"].isoformat()
        
        await self.user_repo.create(user_dict)
        
        # Send welcome email (async via Celery)
        try:
            send_welcome_email.delay(email_norm, f"{first_name} {last_name}")
        except Exception as e:
            logger.warning(f"Failed to queue welcome email: {e}")
        
        logger.info(f"User registered: {email_norm}")
        return self._token_payload_for_user(user_dict)
    
    async def login(self, email: str, password: str) -> Dict[str, Any]:
        """Login user"""
        user = await self.user_repo.get_by_email((email or "").strip().lower())
        if not user:
            raise ValueError("Invalid email or password")
        user["role"] = normalize_role(user.get("role"))

        if _is_unclaimed_account(user):
            raise ValueError(
                "This account needs a password. Please sign up with this email to claim it."
            )

        password_hash = user.get("password_hash")
        if not password_hash or not self._verify_password(password, password_hash):
            raise ValueError("Invalid email or password")
        
        if not user.get("is_active", True):
            raise ValueError("Account is disabled")
        
        # Update last login
        await self.user_repo.update(user["user_id"], {
            "last_login": datetime.now(timezone.utc).isoformat()
        })
        
        logger.info(f"User logged in: {email}")
        return self._token_payload_for_user(user)

    async def lookup_email(self, email: str) -> Dict[str, Any]:
        """Minimal email recognition for checkout UX (no PII beyond flags)."""
        user = await self.user_repo.get_by_email((email or "").strip().lower())
        if not user:
            return {"exists": False, "needs_password": False}
        return {
            "exists": True,
            "needs_password": _is_unclaimed_account(user),
        }

    def _verify_google_id_token(self, id_token: str) -> Dict[str, Any]:
        """Verify a Google / Firebase ID token against GOOGLE_OAUTH_CLIENT_ID."""
        client_id = (settings.google_oauth_client_id or "").strip()
        if not client_id:
            raise ValueError("Google OAuth is not configured")
        try:
            from google.oauth2 import id_token as google_id_token
            from google.auth.transport import requests as google_requests
        except ImportError as exc:
            raise ValueError("Google auth libraries are not installed") from exc
        try:
            return google_id_token.verify_oauth2_token(
                id_token,
                google_requests.Request(),
                client_id,
            )
        except Exception as exc:
            logger.warning("Google ID token verification failed: %s", exc)
            raise ValueError("Invalid Google credential") from exc

    async def oauth_google(
        self,
        id_token: str,
        phone: Optional[str] = None,
        *,
        standalone: bool = False,
    ) -> Dict[str, Any]:
        """
        Upsert a customer from a verified Google ID token.
        Claims unclaimed guest_purchase accounts by email when present.
        """
        claims = self._verify_google_id_token(id_token)
        email_norm = (claims.get("email") or "").strip().lower()
        if not email_norm:
            raise ValueError("Google account did not provide an email")
        if claims.get("email_verified") is False:
            raise ValueError("Google email is not verified")

        given = (claims.get("given_name") or "").strip()
        family = (claims.get("family_name") or "").strip()
        full = (claims.get("name") or "").strip()
        if not given and full:
            parts = full.split()
            given = parts[0]
            family = " ".join(parts[1:]) if len(parts) > 1 else ""
        if not given:
            given = email_norm.split("@")[0]
        if not family:
            family = "User"

        phone_norm = (phone or "").strip()
        picture = claims.get("picture")
        google_sub = claims.get("sub")

        existing = await self.user_repo.get_by_email(email_norm)
        if existing:
            updates: Dict[str, Any] = {
                "last_login": datetime.now(timezone.utc).isoformat(),
                "is_verified": True,
            }
            if _is_unclaimed_account(existing):
                updates.update(
                    {
                        "first_name": given,
                        "last_name": family,
                        "auth_method": "oauth",
                        "account_claimed": True,
                        "oauth_provider": "google",
                        "oauth_sub": google_sub,
                    }
                )
                if phone_norm:
                    updates["phone"] = phone_norm
                logger.info("Guest account claimed via Google OAuth: %s", email_norm)
            else:
                # Link Google on existing password accounts without wiping password.
                if not existing.get("oauth_provider"):
                    updates["oauth_provider"] = "google"
                    updates["oauth_sub"] = google_sub
                if phone_norm and not (existing.get("phone") or "").strip():
                    updates["phone"] = phone_norm
                if picture and not existing.get("profile_image_url"):
                    updates["profile_image_url"] = picture

            updated = await self.user_repo.update(existing["user_id"], updates)
            user = updated or {**existing, **updates}
            user["role"] = normalize_role(user.get("role"))
            if self._phone_missing(user):
                return self._phone_setup_payload(user)
            return self._token_payload_for_user(user, standalone=standalone)

        if not phone_norm:
            # Create account without phone; client must complete phone step
            # before receiving access/refresh JWTs.
            phone_for_create = None
        else:
            phone_for_create = phone_norm

        user = User(
            user_id=generate_id(),
            email=email_norm,
            password_hash=None,
            first_name=given,
            last_name=family,
            phone=phone_for_create,
            role=UserRole.CUSTOMER,
            is_active=True,
            is_verified=True,
            is_discovery_completed=False,
            auth_method="oauth",
            account_claimed=True,
            profile_image_url=picture,
        )
        user_dict = user.model_dump()
        user_dict["oauth_provider"] = "google"
        user_dict["oauth_sub"] = google_sub
        user_dict["created_at"] = user_dict["created_at"].isoformat()
        user_dict["updated_at"] = user_dict["updated_at"].isoformat()
        user_dict["last_login"] = datetime.now(timezone.utc).isoformat()
        await self.user_repo.create(user_dict)
        try:
            send_welcome_email.delay(email_norm, f"{given} {family}")
        except Exception as e:
            logger.warning(f"Failed to queue welcome email: {e}")
        logger.info("User registered via Google OAuth: %s", email_norm)
        if self._phone_missing(user_dict):
            return self._phone_setup_payload(user_dict)
        return self._token_payload_for_user(user_dict, standalone=standalone)

    async def complete_oauth_phone(
        self,
        setup_token: str,
        phone: str,
        *,
        standalone: bool = False,
    ) -> Dict[str, Any]:
        """Exchange a phone_setup token + phone for full app JWTs."""
        phone_norm = (phone or "").strip()
        if len(phone_norm) < 7:
            raise ValueError("Phone number is required")
        try:
            payload = jwt.decode(
                setup_token,
                settings.jwt_secret_key,
                algorithms=[settings.jwt_algorithm],
            )
        except JWTError as exc:
            raise ValueError("Invalid or expired setup token") from exc
        if payload.get("type") != "phone_setup":
            raise ValueError("Invalid setup token type")
        user_id = payload.get("sub")
        user = await self.user_repo.get_by_id(user_id)
        if not user or not user.get("is_active", True):
            raise ValueError("User not found or inactive")
        updated = await self.user_repo.update(user["user_id"], {"phone": phone_norm})
        user = updated or {**user, "phone": phone_norm}
        user["role"] = normalize_role(user.get("role"))
        logger.info("OAuth phone completed for %s", user.get("email"))
        return self._token_payload_for_user(user, standalone=standalone)

    async def upsert_guest_buyer(
        self,
        email: str,
        full_name: str,
        phone: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Upsert a customer from guest store checkout.
        Creates an unclaimed account when email is new; updates contact fields
        on unclaimed accounts; leaves claimed accounts' credentials alone.
        """
        email_norm = (email or "").strip().lower()
        phone_norm = (phone or "").strip() or None
        parts = (full_name or "").strip().split()
        first_name = parts[0] if parts else "Guest"
        last_name = " ".join(parts[1:]) if len(parts) > 1 else "Customer"

        existing = await self.user_repo.get_by_email(email_norm)
        if existing:
            updates: Dict[str, Any] = {}
            if _is_unclaimed_account(existing):
                updates["first_name"] = first_name
                updates["last_name"] = last_name
                if phone_norm:
                    updates["phone"] = phone_norm
                updates["auth_method"] = existing.get("auth_method") or "guest_purchase"
                updates["account_claimed"] = False
            else:
                # Claimed password/oauth accounts: never demote; only fill missing phone.
                if phone_norm and not (existing.get("phone") or "").strip():
                    updates["phone"] = phone_norm
            if updates:
                updated = await self.user_repo.update(existing["user_id"], updates)
                return updated or existing
            return existing

        now = utc_now()
        user = User(
            user_id=generate_id(),
            email=email_norm,
            password_hash=None,
            first_name=first_name,
            last_name=last_name,
            phone=phone_norm,
            role=UserRole.CUSTOMER,
            is_active=True,
            is_verified=False,
            is_discovery_completed=False,
            auth_method="guest_purchase",
            account_claimed=False,
            created_at=now,
            updated_at=now,
        )
        user_dict = user.model_dump()
        user_dict["created_at"] = user_dict["created_at"].isoformat()
        user_dict["updated_at"] = user_dict["updated_at"].isoformat()
        await self.user_repo.create(user_dict)
        logger.info(f"Guest buyer upserted: {email_norm}")
        return user_dict
    
    async def refresh_token(
        self, refresh_token: str, *, standalone: bool = False
    ) -> Dict[str, Any]:
        """Refresh access token"""
        try:
            payload = jwt.decode(
                refresh_token,
                settings.jwt_secret_key,
                algorithms=[settings.jwt_algorithm]
            )
            
            if payload.get("type") != "refresh":
                raise ValueError("Invalid token type")
            
            user_id = payload.get("sub")
            user = await self.user_repo.get_by_id(user_id)
            
            if not user or not user.get("is_active", True):
                raise ValueError("User not found or inactive")
            user["role"] = normalize_role(user.get("role"))
            if user["role"] == "customer" and len((user.get("phone") or "").strip()) < 7:
                raise ValueError("Phone number required to continue")

            # Preserve standalone refresh duration when either the prior token
            # or the current client requests installed-PWA mode.
            use_standalone = standalone or bool(payload.get("standalone"))
            
            # Generate new tokens
            token_data = {
                "sub": user["user_id"],
                "email": user["email"],
                "role": user["role"]
            }
            new_access_token = self._create_access_token(token_data)
            new_refresh_token = self._create_refresh_token(
                token_data, standalone=use_standalone
            )
            
            return {
                "access_token": new_access_token,
                "refresh_token": new_refresh_token,
                "token_type": "bearer",
                "expires_in": settings.access_token_expire_minutes * 60
            }
            
        except JWTError as e:
            raise ValueError(f"Invalid refresh token: {e}")
    
    def verify_token(self, token: str) -> Dict[str, Any]:
        """Verify and decode access token"""
        try:
            payload = jwt.decode(
                token,
                settings.jwt_secret_key,
                algorithms=[settings.jwt_algorithm]
            )
            
            if payload.get("type") != "access":
                raise ValueError("Invalid token type")
            
            return payload
            
        except JWTError as e:
            raise ValueError(f"Invalid token: {e}")
    
    async def get_current_user(self, token: str) -> Dict[str, Any]:
        """Get current user from token"""
        payload = self.verify_token(token)
        user_id = payload.get("sub")
        
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise ValueError("User not found")
        user["role"] = normalize_role(user.get("role"))
        
        # Remove sensitive data
        user.pop("password_hash", None)
        return user
