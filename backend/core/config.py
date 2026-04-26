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
    
    # Celery — when True, tasks run in-process (no Redis/worker needed; use for local dev)
    celery_task_always_eager: bool = False

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
    
    # REVEL POS — live HTTP only (see infrastructure/external/revel_service.py)
    revel_api_url: str = "https://api.revelup.com"
    revel_api_key: str = "mock_revel_key"
    revel_api_secret: str = "mock_revel_secret"
    revel_establishment_id: int = 1
    # e.g. thenaturalpathla -> https://thenaturalpathla.revelup.com/resources/
    revel_subdomain: Optional[str] = None
    # Optional override for sandbox, e.g. https://api-sandbox-revel.revelup.com
    revel_rest_base_url: Optional[str] = None
    revel_http_timeout_seconds: float = 20.0
    revel_enable_hosted_payments: bool = False
    revel_enable_hold_orders: bool = False
    allow_unsigned_webhooks: bool = False
    refund_sla_business_days: int = 3
    # G2 — automatic retry of uncertain card refunds (reconciliation_pending).
    refund_reconciliation_sweep_min_age_minutes: int = 15
    refund_reconciliation_sweep_max_batch: int = 50
    refund_reconciliation_sweep_max_attempts: int = 48
    default_currency: str = "USD"
    # Store tax rate used to validate Revel-returned tax. Single rate for
    # Phase 2 (single establishment). Moved out of hardcoded literal in
    # store_routes; per-establishment rates arrive in Phase 3.
    store_tax_rate: float = 0.0925
    ops_email: Optional[str] = None
    # Relative Revel resource name for hosted payment links (validated in A1 spike).
    revel_hosted_payment_endpoint: str = "HostedPaymentLink"
    revel_webhook_tolerance_seconds: int = 300
    revel_webhook_replay_ttl_seconds: int = 86400

    # Used in booking confirmation emails for absolute links (optional)
    public_app_url: str = "http://localhost:5173"

    class Config:
        env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


settings = get_settings()
