"""
FastAPI application entry point.

Wire up routers, middleware, and lifecycle hooks.
Serves as the single ASGI application for the meeting transcription backend.

CORS is configured via environment variables for production safety.
API prefix is configurable (default /api for development, empty for production).
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router as api_router
from app.config.settings import settings

app = FastAPI(
    title="Speechi - Meeting Transcription & Summarization API",
    description="Audio → Whisper → Claude → JSON (optional Word/PDF).",
    version="0.1.0",
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
    allow_methods=["GET", "POST", "OPTIONS"],
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
    return JSONResponse(
        content={
            "service": "Speechi API",
            "version": "0.1.0",
            "status": "ok",
            "docs": "/docs" if not settings.is_production else None,
            "api_prefix": settings.normalized_api_prefix or "(root)",
            "endpoints": {
                "health": f"{settings.normalized_api_prefix}/health",
                "process_meeting": f"{settings.normalized_api_prefix}/process-meeting",
                "export_docx": f"{settings.normalized_api_prefix}/process-meeting/export-docx",
                "export_pdf": f"{settings.normalized_api_prefix}/process-meeting/export-pdf",
            },
        }
    )


# Include API router with configurable prefix
app.include_router(api_router)


@app.on_event("startup")
async def startup_event():
    """Log configuration on startup."""
    print("=" * 50)
    print("[Speechi API] Starting up...")
    print(f"[Speechi API] Environment: {settings.app_env}")
    print(f"[Speechi API] API prefix: {settings.normalized_api_prefix or '(root)'}")
    print(f"[Speechi API] CORS origins: {settings.cors_origins_list}")
    print(f"[Speechi API] Server: {settings.app_host}:{settings.app_port}")
    print("=" * 50)


# For running with: python -m app.main
if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=not settings.is_production,
    )
