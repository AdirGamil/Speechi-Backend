"""
Application configuration.

Central settings sourced from environment. API keys, CORS origins,
server configuration, and feature flags. Single source of truth for config.

Uses pydantic-settings for type-safe environment variable loading.
"""

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    
    All settings can be overridden via environment variables.
    Variable names are case-insensitive.
    """
    
    # ---- Environment ----
    app_env: str = "development"
    
    # ---- Server ----
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    
    # ---- API Routing ----
    # API prefix (empty string for root-level routes in production)
    # Development: /api
    # Production: "" (empty, routes at root)
    api_prefix: str = "/api"
    
    # ---- CORS ----
    # Comma-separated string of allowed origins (no wildcards in production)
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    
    # ---- API Keys ----
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    
    # ---- Optional API Base URLs ----
    openai_base_url: str | None = None
    anthropic_base_url: str | None = None
    
    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.app_env.lower() == "production"
    
    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS origins string into a list. No wildcards allowed."""
        if not self.cors_origins:
            return []
        origins = [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
        # Filter out wildcards in production
        if self.is_production:
            origins = [o for o in origins if o != "*"]
        return origins
    
    @property
    def normalized_api_prefix(self) -> str:
        """
        Get normalized API prefix.
        Returns empty string if prefix is "/" or empty.
        Ensures prefix starts with "/" if non-empty.
        """
        prefix = self.api_prefix.strip()
        if not prefix or prefix == "/":
            return ""
        if not prefix.startswith("/"):
            prefix = "/" + prefix
        return prefix
    
    class Config:
        # Load from .env file
        env_file = ".env"
        env_file_encoding = "utf-8"
        # Allow extra fields from environment
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.
    
    Uses lru_cache to ensure settings are only loaded once.
    """
    return Settings()


# Convenience instance for direct import
settings = get_settings()
