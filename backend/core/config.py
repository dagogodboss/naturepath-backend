"""
Core Configuration Module - The Natural Path Spa Management System
"""
import os
from functools import lru_cache
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Application
    app_name: str = "The Natural Path Spa"
    app_env: str = "development"
    debug: bool = True
    
    # MongoDB
    mongo_url: str = "mongodb://localhost:27017"
    db_name: str = "natural_path_spa"
    
    # JWT
    jwt_secret_key: str = "natural-path-spa-super-secret-key-2024"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    
    # Redis
    redis_url: str = "redis://localhost:6379/0"
    
    # Email (Resend)
    resend_api_key: Optional[str] = None
    sender_email: str = "onboarding@resend.dev"
    
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
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


settings = get_settings()
