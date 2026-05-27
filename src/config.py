from typing import Literal
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    DATABASE_URL: str = "sqlite:///data/gallery.db"

    # JWT / Auth (see ADR 0003, ADR 0004).
    # For Keycloak:
    #   JWKS_URI   = https://<keycloak-host>/realms/<realm>/protocol/openid-connect/certs
    #   JWT_ISSUER = https://<keycloak-host>/realms/<realm>      (no trailing slash; must match `iss` exactly)
    #   JWT_AUDIENCE = the audience mapped onto gallery-bound tokens (default: prompt-gallery-api)
    JWKS_URI: str = ""
    JWT_ISSUER: str = ""
    JWT_AUDIENCE: str = "prompt-gallery-api"
    JWT_SECRET_KEY: str = ""
    JWKS_CACHE_TTL_SECONDS: int = 3600
    JWT_LEEWAY_SECONDS: int = 60

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

    # Rate limiting (req/min). Multi-axis: per-IP / per-sub / per-azp / per-org_id.
    RATE_LIMIT_ANONYMOUS: int = 30
    RATE_LIMIT_USER: int = 120
    RATE_LIMIT_CLIENT: int = 600
    RATE_LIMIT_ORG: int = 1200

    # Upload
    MAX_UPLOAD_SIZE: int = 5_242_880  # 5 MB

    # Embeddings
    EMBEDDING_MODEL: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    EMBEDDING_USE_FAKE: bool = False

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str) -> str:
        return v

    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @model_validator(mode="after")
    def _require_idp_in_production(self) -> "Settings":
        if self.ENVIRONMENT == "production":
            if not self.JWKS_URI:
                raise ValueError("JWKS_URI is required when ENVIRONMENT=production")
            if not self.JWT_ISSUER:
                raise ValueError("JWT_ISSUER is required when ENVIRONMENT=production")
            if self.JWT_SECRET_KEY:
                raise ValueError(
                    "JWT_SECRET_KEY (HMAC dev fallback) is hard-blocked when ENVIRONMENT=production"
                )
        return self


settings = Settings()
