from typing import Literal
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    DATABASE_URL: str = "sqlite:///data/gallery.db"

    # JWT / Auth
    JWKS_URI: str = ""
    JWT_ISSUER: str = "http://localhost:9000"
    JWT_SECRET_KEY: str = ""
    # Storage
    STORAGE_BACKEND: Literal["local", "s3"] = "local"
    STORAGE_LOCAL_PATH: str = "./uploads"
    S3_BUCKET: str = ""
    S3_REGION: str = "eu-west-1"
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: str = ""

    # CORS
    CORS_ORIGINS: str = "http://localhost:5173"

    # Redis (optional)
    REDIS_URL: str = ""

    # Logging & env
    LOG_LEVEL: Literal["debug", "info", "warning", "error"] = "info"
    ENVIRONMENT: Literal["development", "production", "testing"] = "development"

    # Rate limiting (req/min)
    RATE_LIMIT_ANONYMOUS: int = 30
    RATE_LIMIT_USER: int = 120
    RATE_LIMIT_MACHINE: int = 300

    # Upload
    MAX_UPLOAD_SIZE: int = 5_242_880  # 5 MB

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str) -> str:
        return v

    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
