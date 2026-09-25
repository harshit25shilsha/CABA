"""
Centralized application configuration.

All runtime config is loaded here via pydantic-settings, validated once at
process startup, and imported everywhere else as `from app.core.config import settings`.
Never read os.environ directly anywhere else in the codebase.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from typing import List, Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    LOCAL = "local"
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"

class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    PROJECT_NAME: str = "CABA AI Document Intelligence"
    API_V1_PREFIX: str = "/api/v1"
    ENVIRONMENT: Environment = Environment.LOCAL
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # Comma-separated in .env, e.g. CORS_ORIGINS=http://localhost:3000,https://caba.app
    # Stored raw and parsed via a property — pydantic-settings tries to JSON-decode
    # list-typed env vars before validators run, which breaks plain comma lists.
    CORS_ORIGINS_RAW: str = Field(default="", alias="CORS_ORIGINS")

    @property
    def CORS_ORIGINS(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS_RAW.split(",") if o.strip()]


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_HOST: str
    POSTGRES_PORT: int
    POSTGRES_DB: str

    # Pool tuning — production values; override in .env for local dev if needed
    DB_POOL_SIZE: int
    DB_MAX_OVERFLOW: int
    DB_POOL_TIMEOUT: int
    DB_POOL_RECYCLE: int        # seconds; avoids stale connections
    DB_ECHO: bool

    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def SQLALCHEMY_SYNC_URI(self) -> str:
        """Sync URI for Alembic migrations (asyncpg has no sync driver)."""
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


class RedisSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    REDIS_HOST: str
    REDIS_PORT: int
    REDIS_DB: int
    REDIS_PASSWORD: Optional[str] = None

    @property
    def REDIS_URL(self) -> str:
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"


class CelerySettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    # Separate DB index from cache/session Redis to avoid key collisions
    CELERY_BROKER_DB: int
    CELERY_RESULT_BACKEND_DB: int
    CELERY_TASK_ALWAYS_EAGER: bool       # True only in tests
    CELERY_TASK_TIME_LIMIT: int          # hard kill after 5 min
    CELERY_TASK_SOFT_TIME_LIMIT: int


class SecuritySettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    SECRET_KEY: str         # required, no default — force it to come from .env
    ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    REFRESH_TOKEN_EXPIRE_DAYS: int

    @field_validator("SECRET_KEY")
    @classmethod
    def secret_key_must_be_strong(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters")
        return v


class StorageSettings(BaseSettings):
    """
    Cloudinary is the storage layer for every lifecycle stage (temp, quarantine,
    review, permanent) in ALL environments, including local dev. Local disk is
    never used as the temp-storage layer — it doesn't survive multiple API/worker
    processes. LOCAL_SCRATCH_PATH is only a transient buffer while a file is being
    read for OCR/extraction, never a storage destination.
    """

    model_config = SettingsConfigDict(extra="ignore")

    CLOUDINARY_CLOUD_NAME: Optional[str] = None
    CLOUDINARY_API_KEY: Optional[str] = None
    CLOUDINARY_API_SECRET: Optional[str] = None

    CLOUDINARY_TEMP_FOLDER: str
    CLOUDINARY_QUARANTINE_FOLDER: str
    CLOUDINARY_REVIEW_FOLDER: str
    CLOUDINARY_PERMANENT_FOLDER: str

    LOCAL_SCRATCH_PATH: str = "./storage/scratch"

    MAX_UPLOAD_SIZE_MB: int
    ALLOWED_MIME_TYPES_RAW: str = Field(
        default=(
            "application/pdf,"
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document,"
            "image/jpeg,image/png"
        ),
        alias="ALLOWED_MIME_TYPES",
    )

    @property
    def ALLOWED_MIME_TYPES(self) -> List[str]:
        return [m.strip() for m in self.ALLOWED_MIME_TYPES_RAW.split(",") if m.strip()]


class LLMSettings(BaseSettings):
    """Groq LLM — semantic requirement understanding & explanations."""

    model_config = SettingsConfigDict(extra="ignore")

    GROQ_API_KEY: str
    GROQ_MODEL: str
    GROQ_TIMEOUT_SECONDS: int
    GROQ_MAX_RETRIES: int
    LLM_TEMPERATURE: float          # low temp — deterministic-leaning extraction


class VisionSettings(BaseSettings):
    """
    Vision/document model for EXTRACT_VISUAL — scanned docs, forms,
    layouts, tables. Field names are provider-agnostic on purpose: the
    processor uses an OpenAI-compatible client, so switching provider
    later (Gemini -> Qwen -> a self-hosted vLLM endpoint, etc.) is a
    .env change (VISION_BASE_URL/VISION_MODEL/VISION_API_KEY) plus
    swapping which processor class factory.py registers for
    EXTRACT_VISUAL — never a change to the AIBrain/router/AIProcessor
    core.
 
    Default provider: Google Gemini 2.5 Flash via its OpenAI-compatible
    endpoint, on the free API tier for Phase 1 development.
    """
    
    model_config = SettingsConfigDict(extra ="ignore")
    
    VISION_API_KEY: str = ""
    VISION_MODEL: str
    VISION_BASE_URL: str
    VISION_TIMEOUT_SECONDS: int             # vision calls run slower than text-only
    VISION_MAX_RETRIES: int
    

class OCRSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    TESSERACT_CMD: Optional[str] = None         # override if not on PATH (esp. Windows)
    OCR_LANGUAGE: str = "eng"
    USE_PADDLEOCR: bool = False                  # evaluation flag per architecture doc


class ExternalValidationSettings(BaseSettings):
    """Settings for Java-originated, signed-URL document validation."""

    model_config = SettingsConfigDict(extra="ignore")

    # Empty is allowed only so a newly deployed service can expose health
    # checks; the validation endpoint returns 503 until this is configured.
    AI_BRAIN_SERVICE_API_KEY: str = ""
    CABA_WEBHOOK_URL: str = ""
    CABA_WEBHOOK_HMAC_SECRET: str = ""
    EXTERNAL_FILE_DOWNLOAD_TIMEOUT_SECONDS: float
    JAVA_WEBHOOK_TIMEOUT_SECONDS: float
    PROCESSING_LEASE_SECONDS: int


# Root settings — composes every group above. This is the ONLY object
# imported elsewhere in the app.


class Settings(
    AppSettings,
    DatabaseSettings,
    RedisSettings,
    CelerySettings,
    SecuritySettings,
    StorageSettings,
    LLMSettings,
    VisionSettings,
    OCRSettings,
    ExternalValidationSettings,
):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @model_validator(mode="after")
    def production_safety_checks(self) -> "Settings":
        if self.ENVIRONMENT == Environment.PRODUCTION:
            if self.DEBUG:
                raise ValueError("DEBUG must be False in production")
            if not self.CORS_ORIGINS:
                raise ValueError("CORS_ORIGINS must be explicitly set in production")
            if not self.AI_BRAIN_SERVICE_API_KEY:
                raise ValueError("AI_BRAIN_SERVICE_API_KEY must be configured in production")
            if not self.CABA_WEBHOOK_URL or not self.CABA_WEBHOOK_HMAC_SECRET:
                raise ValueError("Java webhook URL and HMAC secret must be configured in production")
        return self


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance — .env is read once per process."""
    return Settings()


settings = get_settings()
