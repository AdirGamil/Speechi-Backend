"""
FastAPI application entry point.

Wire up routers, middleware, and lifecycle hooks.
Serves as the single ASGI application for the meeting transcription backend.

CORS is configured via environment variables for production safety.
API prefix is configurable (default /api for development, empty for production).
MongoDB connection is established on startup.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router as api_router
from app.api.auth_routes import router as auth_router
from app.config.settings import settings
from app.db.connection import init_db, close_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.
    
    Manages startup and shutdown events.
    """
    # Startup
    print("=" * 50)
    print("[Speechi API] Starting up...")
    print(f"[Speechi API] Environment: {settings.app_env}")
    print(f"[Speechi API] API prefix: {settings.normalized_api_prefix or '(root)'}")
    print(f"[Speechi API] CORS origins: {settings.cors_origins_list}")
    print(f"[Speechi API] Server: {settings.app_host}:{settings.app_port}")
    
    # Initialize database
    await init_db()
    
    print("=" * 50)
    
    yield
    
    # Shutdown
    print("[Speechi API] Shutting down...")
    await close_db()


app = FastAPI(
    title="Speechi - Meeting Transcription & Summarization API",
    description="Audio → Whisper → Claude → JSON (optional Word/PDF). Includes user authentication.",
    version="0.2.0",
    lifespan=lifespan,
    # Disable docs in production if needed
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
)

# CORS middleware - origins loaded from environment
# In production, this is restricted to the frontend domain only
# No wildcards allowed in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Accept"],
)


# Root endpoint - catches requests to /
# Returns API info instead of 404
@app.get("/", include_in_schema=False)
async def root():
    """
    Root endpoint. Returns API information.
    Useful for health checks and service discovery.
    """
    prefix = settings.normalized_api_prefix
    return JSONResponse(
        content={
            "service": "Speechi API",
            "version": "0.2.0",
            "status": "ok",
            "docs": "/docs" if not settings.is_production else None,
            "api_prefix": prefix or "(root)",
            "endpoints": {
                "health": f"{prefix}/health",
                "process_meeting": f"{prefix}/process-meeting",
                "auth_register": f"{prefix}/auth/register",
                "auth_login": f"{prefix}/auth/login",
                "auth_me": f"{prefix}/auth/me",
            },
        }
    )


# Include API routers with configurable prefix
app.include_router(api_router)
app.include_router(auth_router, prefix=settings.normalized_api_prefix)


# For running with: python -m app.main
if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=not settings.is_production,
    )
