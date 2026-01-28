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
    
    # ---- CORS ----
    # Comma-separated string of allowed origins
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
        """Parse CORS origins string into a list."""
        if not self.cors_origins:
            return []
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
    
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
