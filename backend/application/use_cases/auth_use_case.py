"""
Authentication Use Cases - Application Layer
"""
import logging
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from passlib.context import CryptContext
from jose import jwt, JWTError
from core.config import settings
from core.rbac import normalize_role
from domain.entities import User, UserRole, generate_id, utc_now
from infrastructure.repositories import MongoUserRepository
from workers.notification_worker import send_welcome_email
from application.auth_attempt_limits import AttemptLimiter
from application.claim_proof import RedisClaimProofStore
from application.refresh_sessions import RedisRefreshSessionStore, legacy_refresh_hash

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthUnavailable(Exception):
    """Session storage is required and currently unavailable."""


def allows_normal_session(user: Dict[str, Any]) -> bool:
    """Normal access and refresh tokens require a verified email.

    New password registration stores is_verified false and does not return a
    session. OTP send/verify, guest checkout, and sign-in of an already
    verified account do not need a pre-verify bearer token. OAuth accounts are
    verified by the identity provider. Records that predate this flag keep
    access when the field is absent; an explicit false does not.
    """
    if user.get("auth_method") == "oauth":
        return user.get("is_verified", True) is not False
    if user.get("is_verified") is True:
        return True
    if "is_verified" not in user or user.get("is_verified") is None:
        return True
    return False


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
    
    def __init__(
        self,
        user_repo: MongoUserRepository,
        *,
        claim_store=None,
        session_store=None,
        attempt_limiter: Optional[AttemptLimiter] = None,
    ):
        self.user_repo = user_repo
        self.claim_store = claim_store if claim_store is not None else RedisClaimProofStore()
        self.session_store = session_store if session_store is not None else RedisRefreshSessionStore()
        self.attempt_limiter = attempt_limiter

    async def _attempts(self) -> AttemptLimiter:
        if self.attempt_limiter is not None:
            return self.attempt_limiter
        from infrastructure.cache import get_cache_service

        return AttemptLimiter(await get_cache_service())

    async def issue_claim_proof(self, user: Dict[str, Any]) -> str:
        """Return a single-use claim credential bound to this account."""
        email = (user.get("email") or "").strip().lower()
        token = await self.claim_store.issue(email=email, user_id=user["user_id"])
        if not token:
            raise AuthUnavailable("Verification is temporarily unavailable")
        return token

    async def _consume_claim_proof(self, email: str, token: Optional[str]) -> Optional[str]:
        if not token:
            return None
        return await self.claim_store.consume(email=email, token=token)
    
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
        self,
        data: dict,
        *,
        standalone: bool = False,
        jti: Optional[str] = None,
        session_exp: Optional[datetime] = None,
    ) -> str:
        to_encode = data.copy()
        days = (
            settings.refresh_token_expire_days_standalone
            if standalone
            else settings.refresh_token_expire_days
        )
        expire = datetime.now(timezone.utc) + timedelta(days=days)
        if session_exp is not None:
            cap = session_exp if session_exp.tzinfo else session_exp.replace(tzinfo=timezone.utc)
            if cap < expire:
                expire = cap
            to_encode["session_exp"] = int(cap.timestamp())
        to_encode.update({"exp": expire, "type": "refresh"})
        if jti:
            to_encode["jti"] = jti
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

    async def _issue_session_tokens(
        self,
        user: Dict[str, Any],
        *,
        standalone: bool = False,
        session_exp: Optional[datetime] = None,
        sid: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Issue a normal session. Absolute expiry is fixed for the session."""
        if not allows_normal_session(user):
            raise ValueError("Verify your email before signing in")
        now = datetime.now(timezone.utc)
        if session_exp is None:
            days = (
                settings.refresh_token_expire_days_standalone
                if standalone
                else settings.refresh_token_expire_days
            )
            session_exp = now + timedelta(days=days)
        elif session_exp.tzinfo is None:
            session_exp = session_exp.replace(tzinfo=timezone.utc)
        if session_exp <= now:
            raise ValueError("Invalid refresh token")

        role = normalize_role(user.get("role"))
        sid = sid or secrets.token_urlsafe(18)
        jti = secrets.token_urlsafe(18)
        epoch = int(user.get("session_epoch") or 0)
        identity = {
            "sub": user["user_id"],
            "email": user["email"],
            "role": role,
            "sid": sid,
            "epoch": epoch,
        }
        refresh_token = self._create_refresh_token(
            identity,
            standalone=standalone,
            jti=jti,
            session_exp=session_exp,
        )
        refresh_payload = jwt.decode(
            refresh_token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        refresh_exp = datetime.fromtimestamp(int(refresh_payload["exp"]), tz=timezone.utc)
        stored = await self.session_store.save(
            jti=jti,
            sid=sid,
            user_id=user["user_id"],
            refresh_ttl=max(1, int((refresh_exp - now).total_seconds())),
            session_ttl=max(1, int((session_exp - now).total_seconds())),
            meta={
                "session_exp": int(session_exp.timestamp()),
                "standalone": bool(standalone),
                "epoch": epoch,
            },
        )
        if not stored:
            raise AuthUnavailable("Authentication is temporarily unavailable")
        return {
            "access_token": self._create_access_token(identity),
            "refresh_token": refresh_token,
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
        role: UserRole = UserRole.CUSTOMER,
        claim_token: Optional[str] = None,
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
                # The claim credential is issued only to the caller that verified
                # the OTP, and it is bound to this account's user id.
                bound_user_id = await self._consume_claim_proof(email_norm, claim_token)
                if not bound_user_id or bound_user_id != existing["user_id"]:
                    raise ValueError(
                        "Verify your email before claiming this account. "
                        "Request a code via /api/auth/send-verification-otp, "
                        "then /api/auth/verify-email-otp."
                    )
                updated = await self.user_repo.claim_if_unclaimed(
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
                        "session_epoch": int(existing.get("session_epoch") or 0) + 1,
                    },
                )
                if not updated:
                    raise ValueError("This account was already claimed")
                logger.info(f"Guest account claimed via register: {email_norm}")
                try:
                    send_welcome_email.delay(email_norm, f"{first_name} {last_name}")
                except Exception as e:
                    logger.warning(f"Failed to queue welcome email: {e}")
                return await self._issue_session_tokens(updated)
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
        return {
            "verification_required": True,
            "email": email_norm,
            "user": self._user_public(user_dict),
        }
    
    async def login(
        self,
        email: str,
        password: str,
        *,
        client_ip: str = "unknown",
        standalone: bool = False,
    ) -> Dict[str, Any]:
        """Login user"""
        email_norm = (email or "").strip().lower()
        attempts = await self._attempts()
        await attempts.assert_login_allowed(email_norm, client_ip or "unknown")
        user = await self.user_repo.get_by_email(email_norm)
        if not user:
            await attempts.record_login_failure(email_norm, client_ip or "unknown")
            raise ValueError("Invalid email or password")
        user["role"] = normalize_role(user.get("role"))

        if _is_unclaimed_account(user):
            raise ValueError(
                "This account needs a password. Please sign up with this email to claim it."
            )

        password_hash = user.get("password_hash")
        if not password_hash or not self._verify_password(password, password_hash):
            await attempts.record_login_failure(email_norm, client_ip or "unknown")
            raise ValueError("Invalid email or password")
        
        if not user.get("is_active", True):
            raise ValueError("Account is disabled")

        if not allows_normal_session(user):
            raise ValueError("Verify your email before signing in")
        
        # Update last login
        await self.user_repo.update(user["user_id"], {
            "last_login": datetime.now(timezone.utc).isoformat()
        })
        await attempts.clear_login_failures(email_norm)
        
        logger.info(f"User logged in: {email_norm}")
        return await self._issue_session_tokens(user, standalone=standalone)

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
            return await self._issue_session_tokens(user, standalone=standalone)

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
        return await self._issue_session_tokens(user_dict, standalone=standalone)

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
        return await self._issue_session_tokens(user, standalone=standalone)

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
    
    def _session_deadline(self, payload: Dict[str, Any]) -> datetime:
        raw = payload.get("session_exp")
        if raw is None:
            raw = payload.get("exp")
        return datetime.fromtimestamp(int(raw), tz=timezone.utc)

    async def refresh_token(
        self, refresh_token: str, *, standalone: bool = False
    ) -> Dict[str, Any]:
        """Rotate a one-time refresh credential. The client mode cannot extend it."""
        del standalone  # Session length is fixed at issuance.
        try:
            payload = jwt.decode(
                refresh_token,
                settings.jwt_secret_key,
                algorithms=[settings.jwt_algorithm]
            )
        except JWTError as e:
            raise ValueError(f"Invalid refresh token: {e}") from e

        if payload.get("type") != "refresh":
            raise ValueError("Invalid token type")

        user_id = payload.get("sub")
        user = await self.user_repo.get_by_id(user_id)
        if not user or not user.get("is_active", True):
            raise ValueError("User not found or inactive")
        user["role"] = normalize_role(user.get("role"))
        if not allows_normal_session(user):
            raise ValueError("Verify your email before signing in")
        if user["role"] == "customer" and len((user.get("phone") or "").strip()) < 7:
            raise ValueError("Phone number required to continue")
        token_epoch = int(payload.get("epoch") or 0)
        if token_epoch != int(user.get("session_epoch") or 0):
            raise ValueError("Session is no longer valid")

        deadline = self._session_deadline(payload)
        if deadline <= datetime.now(timezone.utc):
            raise ValueError("Invalid refresh token")

        # Only the flag stored at session creation may use the longer lifetime.
        use_standalone = bool(payload.get("standalone"))
        sid = payload.get("sid")
        jti = payload.get("jti")
        if jti:
            outcome = await self.session_store.consume(str(jti))
            if outcome == "unavailable":
                raise AuthUnavailable("Authentication is temporarily unavailable")
            if outcome == "grace":
                raise ValueError("Invalid refresh token")
            if outcome != "consumed":
                if sid:
                    await self.session_store.revoke(str(sid))
                raise ValueError("Invalid refresh token")
            if sid:
                state = await self.session_store.session_state(str(sid), user["user_id"])
                if state == "revoked":
                    raise ValueError("Invalid refresh token")
        else:
            first_use = await self.session_store.consume_legacy(legacy_refresh_hash(refresh_token))
            if first_use is None:
                raise AuthUnavailable("Authentication is temporarily unavailable")
            if not first_use:
                raise ValueError("Invalid refresh token")
            sid = None

        return await self._issue_session_tokens(
            user,
            standalone=use_standalone,
            session_exp=deadline,
            sid=str(sid) if sid else None,
        )

    async def logout(self, refresh_token: str) -> None:
        """Revoke the server session for this refresh credential."""
        if not refresh_token:
            return
        try:
            payload = jwt.decode(
                refresh_token,
                settings.jwt_secret_key,
                algorithms=[settings.jwt_algorithm],
            )
        except JWTError:
            return
        if payload.get("type") != "refresh":
            return
        sid = payload.get("sid")
        if sid:
            await self.session_store.revoke(str(sid))
            return
        if not payload.get("jti"):
            await self.session_store.consume_legacy(legacy_refresh_hash(refresh_token))
    
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
        if not user.get("is_active", True):
            raise ValueError("User account is disabled")
        if not allows_normal_session(user):
            raise ValueError("Email verification required")
        token_epoch = int(payload.get("epoch") or 0)
        if token_epoch != int(user.get("session_epoch") or 0):
            raise ValueError("Session is no longer valid")
        sid = payload.get("sid")
        if sid:
            state = await self.session_store.session_state(str(sid), user["user_id"])
            if state == "revoked":
                raise ValueError("Session is no longer valid")
        user["role"] = normalize_role(user.get("role"))
        
        # Remove sensitive data
        user.pop("password_hash", None)
        return user
