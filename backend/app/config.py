"""Configuration settings for Saral AI backend."""

import os
from functools import lru_cache
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Supabase Configuration
    SUPABASE_URL: str = "https://mock.supabase.co"
    SUPABASE_PUBLISHABLE_KEY: str = "sb_publishable_anon_key"
    SUPABASE_SERVICE_ROLE_KEY: str = "sb_service_role_secret_key"
    SUPABASE_SECRET_KEY: str = "sb_service_role_secret_key"
    SUPABASE_JWT_SECRET: str = "super_secret_supabase_jwt_signing_key"

    # AI & Groq Configuration
    GROQ_API_KEY: str = "gsk_mock_saral_groq_api_key_for_testing"
    LLM_MODEL: str = "llama-3.3-70b-versatile"

    # Security & Internal Service Secrets
    CLEANUP_SECRET: str = "saral_cleanup_cron_secret_auth_token_7766"
    WORKER_SECRET: str = "saral_worker_shared_secret_secure_key_9988"
    WORKER_SHARED_SECRET: str = "saral_worker_shared_secret_secure_key_9988"

    # Domain allowlist for browser worker and workflows
    ALLOWED_DOMAINS: List[str] = [
        "mock-portal.local",
        "127.0.0.1",
        "localhost",
        "uidai.gov.in",
        "myaadhaar.uidai.gov.in",
        "supabase.co",
        "rsftbslckmdkynprmpin.supabase.co",
    ]

    # Database & Storage
    DATABASE_URL: str = ""
    STORAGE_BUCKET: str = "documents"

    # Environment & Logging
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"

    # Rate limiting
    CHAT_RATE_LIMIT: str = "30/minute"
    INPUT_RATE_LIMIT: str = "10/minute"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
