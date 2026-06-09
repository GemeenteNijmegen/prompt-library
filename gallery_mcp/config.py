from pydantic_settings import BaseSettings, SettingsConfigDict


class McpSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    GALLERY_API_URL: str = "http://localhost:8000"
    MCP_HOST: str = "0.0.0.0"
    MCP_PORT: int = 8001
    GALLERY_REQUEST_TIMEOUT: float = 30.0
    # Public URL of this MCP server — used as the `resource` identifier in
    # /.well-known/oauth-protected-resource and in WWW-Authenticate pointers.
    MCP_RESOURCE_URL: str = "http://localhost:8001"
    # Keycloak realm URL advertised as the authorization server.
    KEYCLOAK_REALM_URL: str = "http://localhost:8080/realms/nijmegen"


settings = McpSettings()
