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


class AuthUseCase:
    """Authentication use cases"""
    
    def __init__(self, user_repo: MongoUserRepository):
        self.user_repo = user_repo
    
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
    
    def _create_refresh_token(self, data: dict) -> str:
        to_encode = data.copy()
        expire = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
        to_encode.update({"exp": expire, "type": "refresh"})
        return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    
    async def register(
        self,
        email: str,
        password: str,
        first_name: str,
        last_name: str,
        phone: Optional[str] = None,
        role: UserRole = UserRole.CUSTOMER
    ) -> Dict[str, Any]:
        """Register a new user"""
        # Check if user exists
        existing = await self.user_repo.get_by_email(email)
        if existing:
            raise ValueError("User with this email already exists")
        
        # Create user
        canonical_role = UserRole(normalize_role(role.value))
        user = User(
            user_id=generate_id(),
            email=email,
            password_hash=self._hash_password(password),
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            role=canonical_role,
            is_active=True,
            is_verified=False,
            is_discovery_completed=False,
        )
        
        user_dict = user.model_dump()
        user_dict["created_at"] = user_dict["created_at"].isoformat()
        user_dict["updated_at"] = user_dict["updated_at"].isoformat()
        
        await self.user_repo.create(user_dict)
        
        # Send welcome email (async via Celery)
        try:
            send_welcome_email.delay(email, f"{first_name} {last_name}")
        except Exception as e:
            logger.warning(f"Failed to queue welcome email: {e}")
        
        # Generate tokens
        token_data = {"sub": user.user_id, "email": email, "role": user.role.value}
        access_token = self._create_access_token(token_data)
        refresh_token = self._create_refresh_token(token_data)
        
        logger.info(f"User registered: {email}")
        
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": settings.access_token_expire_minutes * 60,
            "user": {
                "user_id": user.user_id,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "role": user.role.value
            }
        }
    
    async def login(self, email: str, password: str) -> Dict[str, Any]:
        """Login user"""
        user = await self.user_repo.get_by_email(email)
        if not user:
            raise ValueError("Invalid email or password")
        user["role"] = normalize_role(user.get("role"))
        
        if not self._verify_password(password, user["password_hash"]):
            raise ValueError("Invalid email or password")
        
        if not user.get("is_active", True):
            raise ValueError("Account is disabled")
        
        # Update last login
        await self.user_repo.update(user["user_id"], {
            "last_login": datetime.now(timezone.utc).isoformat()
        })
        
        # Generate tokens
        token_data = {
            "sub": user["user_id"],
            "email": user["email"],
            "role": user["role"]
        }
        access_token = self._create_access_token(token_data)
        refresh_token = self._create_refresh_token(token_data)
        
        logger.info(f"User logged in: {email}")
        
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": settings.access_token_expire_minutes * 60,
            "user": {
                "user_id": user["user_id"],
                "email": user["email"],
                "first_name": user["first_name"],
                "last_name": user["last_name"],
                "role": user["role"]
            }
        }
    
    async def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
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
            
            # Generate new tokens
            token_data = {
                "sub": user["user_id"],
                "email": user["email"],
                "role": user["role"]
            }
            new_access_token = self._create_access_token(token_data)
            new_refresh_token = self._create_refresh_token(token_data)
            
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
