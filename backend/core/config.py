"""
Core Configuration Module - The Natural Path Spa Management System
"""
import os
from functools import lru_cache
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings
from typing import Optional, List


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Application
    app_name: str = "The Natural Path Spa"
    app_env: str = "development"
    debug: bool = True
    deployment_target: str = "local"  # local | aws
    use_docker_network: bool = False
    cors_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    
    # MongoDB
    mongo_url: Optional[str] = None
    mongo_host_local: str = "127.0.0.1"
    mongo_host_docker: str = "mongodb"
    mongo_port: int = 27017
    db_name: str = "natural_path_spa"
    
    # JWT
    jwt_secret_key: str = "natural-path-spa-super-secret-key-2024"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    
    # Redis
    redis_url: Optional[str] = None
    redis_host_local: str = "127.0.0.1"
    redis_host_docker: str = "redis"
    redis_port: int = 6379
    redis_db: int = 0
    
    # Email (Resend)
    resend_api_key: Optional[str] = None
    sender_email: str = "onboarding@resend.dev"
    # Email (SMTP fallback)
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_use_tls: bool = True
    smtp_sender_email: Optional[str] = None

    @field_validator("smtp_port", mode="before")
    @classmethod
    def _normalize_smtp_port(cls, value):
        if value in ("", None):
            return 587
        return value

    @field_validator("smtp_use_tls", mode="before")
    @classmethod
    def _normalize_smtp_tls(cls, value):
        if value in ("", None):
            return True
        return value

    @model_validator(mode="after")
    def _hydrate_runtime_urls(self):
        use_docker = self.use_docker_network or self.deployment_target.lower() == "aws"
        if not self.mongo_url:
            mongo_host = self.mongo_host_docker if use_docker else self.mongo_host_local
            self.mongo_url = f"mongodb://{mongo_host}:{self.mongo_port}"
        if not self.redis_url:
            redis_host = self.redis_host_docker if use_docker else self.redis_host_local
            self.redis_url = f"redis://{redis_host}:{self.redis_port}/{self.redis_db}"
        if self.app_env.lower() in ("production", "prod"):
            if self.jwt_secret_key == "natural-path-spa-super-secret-key-2024":
                raise ValueError("JWT_SECRET_KEY must be overridden in production")
            if "*" in self.cors_origins:
                raise ValueError("CORS wildcard is not allowed in production")
        return self

    @property
    def cors_origins(self) -> List[str]:
        return [v.strip() for v in self.cors_allowed_origins.split(",") if v.strip()]
    
    # SMS (Twilio)
    twilio_account_sid: Optional[str] = None
    twilio_auth_token: Optional[str] = None
    twilio_phone_number: Optional[str] = None
    
    # S3
    s3_bucket_name: str = "natural-path-spa"
    s3_access_key: Optional[str] = None
    s3_secret_key: Optional[str] = None
    s3_region: str = "us-east-1"
    s3_endpoint_url: Optional[str] = None
    
    # REVEL POS (Mock)
    revel_api_url: str = "https://api.revelup.com"
    revel_api_key: str = "mock_revel_key"
    revel_api_secret: str = "mock_revel_secret"
    revel_establishment_id: int = 1

    class Config:
        env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


settings = get_settings()
