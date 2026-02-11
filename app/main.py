# app/main.py
# labels-service main entrypoint
# - Initialize logger
# - Mount API routers
# - Global middleware / exception handler
# - Health check and API root info
# - Lifespan context manages JobManager
# - Global config provided by app/config.py (pydantic-settings)

from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from prometheus_client import Gauge
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.responses import Response

from app import SERVICE_NAME, VERSION
from app.api import print_jobs
from app.config import settings
from app.core.limiter import limiter
from app.core.logger import setup_logger
from app.services.job_manager import JobManager

# Custom Prometheus gauges (business metrics)
GAUGE_QUEUE_SIZE = Gauge(
    "jobs_queue_size", "Number of jobs waiting in queue"
)
GAUGE_ACTIVE_WORKERS = Gauge(
    "jobs_active_workers", "Number of workers currently processing jobs"
)
GAUGE_TOTAL_SUBMITTED = Gauge(
    "jobs_total_submitted", "Total jobs submitted since startup"
)


# Lifespan: startup / shutdown management
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifecycle: manage JobManager on startup/shutdown."""
    app.state.job_manager = JobManager()
    app.state.job_manager.start_workers()
    app.state.start_time = datetime.now(UTC)
    logger.info("JobManager started in lifespan")
    try:
        yield
    finally:
        await app.state.job_manager.stop_workers()
        logger.info("JobManager stopped in lifespan")


# Initialize logger and FastAPI app
try:
    setup_logger(settings.LOG_LEVEL, settings.LOG_FORMAT)
except Exception as e:
    import logging

    logging.basicConfig(level=logging.DEBUG)
    logging.error(f"Logger setup failed, fallback to std logging: {e}")

app = FastAPI(
    title=SERVICE_NAME,
    version=VERSION,
    description="FastAPI microservice for batch label printing using gLabels CLI",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)


@app.middleware("http")
async def request_id_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    header_name = settings.REQUEST_ID_HEADER
    request_id = request.headers.get(header_name) or uuid4().hex
    request.state.request_id = request_id

    with logger.contextualize(request_id=request_id):
        response = await call_next(request)

    response.headers[header_name] = request_id
    return response

def _split_csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


# CORS Middleware (simple whitelist)
origins = _split_csv(settings.CORS_ALLOW_ORIGINS)
if origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(
    RateLimitExceeded, _rate_limit_exceeded_handler  # type: ignore[arg-type]
)
app.add_middleware(SlowAPIMiddleware)

# Prometheus metrics
if settings.ENABLE_METRICS:
    def _update_custom_gauges(info: Any) -> None:
        """Callback: update business gauges on every request."""
        jm = getattr(app.state, "job_manager", None)
        if jm and hasattr(jm, "queue"):
            GAUGE_QUEUE_SIZE.set(jm.queue.qsize())
            GAUGE_ACTIVE_WORKERS.set(
                sum(1 for j in jm.jobs.values() if j["status"] == "running")
            )
            GAUGE_TOTAL_SUBMITTED.set(jm.jobs_total)

    instrumentator = Instrumentator()
    instrumentator.instrument(app).expose(
        app, endpoint="/metrics", include_in_schema=False
    )
    instrumentator.add(lambda info: _update_custom_gauges(info))


# Global Exception Handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "-")
    logger.bind(request_id=request_id).exception(
        f"Unhandled error on {request.url.path}: {exc}"
    )
    response = JSONResponse(status_code=500, content={"detail": "Internal Server Error"})
    response.headers[settings.REQUEST_ID_HEADER] = request_id
    return response


# Health Check (lightweight)
@app.get("/health", tags=["system"], summary="Health check")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


# API root: service info + documentation links
@app.get("/", tags=["system"], summary="API root information")
async def api_root(request: Request) -> dict[str, Any]:
    start_time: datetime = request.app.state.start_time
    uptime_td: timedelta = datetime.now(UTC) - start_time
    return {
        "service": SERVICE_NAME,
        "version": VERSION,
        "uptime": str(uptime_td),
        "start_time": start_time.isoformat() + "Z",
        "docs": "/docs",
        "redoc": "/redoc",
        "openapi": "/openapi.json",
    }


# Mount API Routers
app.include_router(print_jobs.router)  # no version prefix, mounted directly


# Entry point: use `python -m app.main`
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.RELOAD,  # controlled via environment variable
        access_log=True,
    )
