"""
FastAPI application entry point.

Wire up routers, middleware, and lifecycle hooks.
Serves as the single ASGI application for the meeting transcription backend.

CORS is configured via environment variables for production safety.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as api_router
from app.config.settings import settings

app = FastAPI(
    title="Meeting Transcription & Summarization API",
    description="Audio → Whisper → Claude → JSON (optional Word/PDF).",
    version="0.1.0",
    # In production, you might want to disable docs
    # docs_url=None if settings.is_production else "/docs",
    # redoc_url=None if settings.is_production else "/redoc",
)

# CORS middleware - origins loaded from environment
# In production, this should be restricted to the frontend domain only
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Include API router (all routes are under /api prefix)
app.include_router(api_router)


@app.on_event("startup")
async def startup_event():
    """Log configuration on startup."""
    print(f"[Speechi] Environment: {settings.app_env}")
    print(f"[Speechi] CORS origins: {settings.cors_origins_list}")
    print(f"[Speechi] Server: {settings.app_host}:{settings.app_port}")


# For running with: python -m app.main
if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=not settings.is_production,
    )
