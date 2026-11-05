import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import get_settings, settings
from app.core.logging import setup_logging
from app.db.base import Base
from app.db.session import engine, SessionLocal
from app.api.v1.router import api_v1_router
from app.services.project_service import ProjectService
from app.services.incident_service import IncidentService

logger = logging.getLogger("tracemind.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager: sets up database tables and seeds demo data on startup."""
    active_settings = get_settings()
    setup_logging()
    logger.info("Initializing TraceMind backend v%s (%s)", active_settings.APP_VERSION, active_settings.ENVIRONMENT)

    if active_settings.DEMO_MODE and active_settings.ENVIRONMENT not in ("test", "testing"):
        try:
            logger.info("DEMO_MODE=True: Ensuring database tables exist...")
            Base.metadata.create_all(bind=engine)

            db = SessionLocal()
            try:
                proj_svc = ProjectService(db)
                proj_svc.ensure_default_seed()
                inc_svc = IncidentService(db)
                inc_svc.ensure_default_seed()
                logger.info("Demo database seeded successfully with default tenant and telemetry.")
            finally:
                db.close()
        except Exception as exc:
            logger.warning("Auto-seed or schema creation skipped/failed: %s", exc)

    yield

    logger.info("TraceMind backend shutting down gracefully.")


app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "TraceMind Backend API — Understand failures. Find root causes. Restore reliability.\n\n"
        "Distributed systems observability and automated incident intelligence backend."
    ),
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# CORS configuration for frontend clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global error handlers
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "Unprocessable Entity",
            "message": "Input validation failed on request parameters or payload.",
            "detail": jsonable_encoder(exc.errors()),
            "details": jsonable_encoder(exc.errors()),
        },
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    detail_str = exc.detail if isinstance(exc.detail, str) else "HTTP Exception"
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": detail_str,
            "detail": exc.detail,
            "status_code": exc.status_code,
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled server error: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal Server Error",
            "message": "An unexpected error occurred while processing the request.",
        },
    )


# Root landing endpoint
@app.get("/", summary="API Root", tags=["Meta"])
def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "tagline": "Understand failures. Find root causes. Restore reliability.",
        "docs_url": "/docs",
        "health_check": f"{settings.API_V1_PREFIX}/health",
        "ready_check": f"{settings.API_V1_PREFIX}/ready",
    }


# Include API v1 router
app.include_router(api_v1_router, prefix=settings.API_V1_PREFIX)

