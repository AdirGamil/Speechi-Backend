"""
FastAPI application entry point.

Wire up routers, middleware, and lifecycle hooks.
Serves as the single ASGI application for the meeting transcription backend.

CORS: Configured via CORS_ORIGINS env, applied before any route.
Middleware order: logging (innermost) then CORS (outermost) so all responses get CORS headers.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config.settings import settings
from app.db.connection import init_db, close_db

logger = logging.getLogger("speechi")
# Ensure request log lines appear (e.g. [REQ] OPTIONS /auth/login, [RES] 200)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.
    Manages startup and shutdown events.
    """
    print("=" * 50)
    print("[Speechi API] Starting up...")
    print(f"[Speechi API] Environment: {settings.app_env}")
    print(f"[Speechi API] API prefix: {settings.normalized_api_prefix or '(root)'}")
    print(f"[Speechi API] CORS origins: {settings.cors_origins_list}")
    print(f"[Speechi API] Server: {settings.app_host}:{settings.app_port}")
    await init_db()
    print("=" * 50)
    yield
    print("[Speechi API] Shutting down...")
    await close_db()


# Create app first; middleware and routes are added below in correct order.
app = FastAPI(
    title="Speechi - Meeting Transcription & Summarization API",
    description="Audio → Whisper → Claude → JSON (optional Word/PDF). Includes user authentication.",
    version="0.2.0",
    lifespan=lifespan,
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
)

# 1) Request logging middleware (innermost) – runs first on request, last on response
@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info("[REQ] %s %s", request.method, request.url)
    response = await call_next(request)
    logger.info("[RES] %s", response.status_code)
    return response

# 2) CORS middleware (outermost) – MUST be registered before routers so all responses get CORS headers.
#    Parsed from ENV: CORS_ORIGINS is split into a list; never pass a raw string to allow_origins.
#    allow_credentials=True requires frontend to use credentials: "include" for cross-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# 3) Global exception handler – ensures 500 responses are JSON and still go through CORS
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )

# 4) Root endpoint (no prefix)
@app.get("/", include_in_schema=False)
async def root():
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

# 5) Include routers ONLY after CORS and middleware. Paths match frontend:
#    API_PREFIX empty => /auth/login; API_PREFIX=/api => /api/auth/login
from app.api.routes import router as api_router
from app.api.auth_routes import router as auth_router

app.include_router(api_router)
app.include_router(auth_router, prefix=settings.normalized_api_prefix)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=not settings.is_production,
    )
