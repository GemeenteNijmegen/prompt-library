from pydantic_settings import BaseSettings, SettingsConfigDict


class McpSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    GALLERY_API_URL: str = "http://localhost:8000"
    MCP_HOST: str = "0.0.0.0"
    MCP_PORT: int = 8001
    GALLERY_REQUEST_TIMEOUT: float = 30.0


settings = McpSettings()
