# app/main.py
# labels-service main entrypoint
# - Initialize logger
# - Mount API routers
# - Global middleware / exception handler
# - Health check and API root info
# - Lifespan context manages JobManager
# - Global config provided by app/config.py (pydantic-settings)

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from app.api import print_jobs
from app.config import settings
from app.core.logger import setup_logger
from app.core.version import SERVICE_NAME, VERSION
from app.services.job_manager import JobManager


# Lifespan: startup / shutdown management
@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifecycle: manage JobManager on startup/shutdown."""
    app.state.job_manager = JobManager()
    app.state.job_manager.start_workers()
    app.state.start_time = datetime.now(timezone.utc)
    logger.info("JobManager started in lifespan")
    try:
        yield
    finally:
        await app.state.job_manager.stop_workers()
        logger.info("JobManager stopped in lifespan")


# Initialize logger and FastAPI app
try:
    setup_logger(settings.LOG_LEVEL)
except Exception as e:
    import logging

    logging.basicConfig(level=logging.DEBUG)
    logging.error(f"Logger setup failed, fallback to std logging: {e}")

app = FastAPI(
    title=SERVICE_NAME,
    version=VERSION,
    description="Label generation microservice (gLabels backend)",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

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


# Global Exception Handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled error on {request.url.path}: {exc}")
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


# Health Check (lightweight)
@app.get("/health", tags=["system"], summary="Health check")
async def health_check():
    return {"status": "ok"}


# API root meta info
@app.get("/", tags=["system"], summary="API root information")
async def api_root():
    return {
        "service": SERVICE_NAME,
        "version": VERSION,
        "docs": "/docs",
        "redoc": "/redoc",
        "openapi": "/openapi.json",
    }


# Service Info (uptime, workers, queue size, jobs_total)
@app.get("/info", tags=["system"], summary="Service information")
async def service_info(request: Request):
    """
    Show service runtime information:
    - service name & version
    - worker count
    - current queue size
    - total submitted jobs
    - uptime (human readable)
    - start time (ISO8601 UTC)
    """
    start_time: datetime = request.app.state.start_time
    uptime_td: timedelta = datetime.now(timezone.utc) - start_time

    job_manager: JobManager = request.app.state.job_manager

    return {
        "service": SERVICE_NAME,
        "version": VERSION,
        "workers": len(job_manager.workers),
        "queue_size": job_manager.queue.qsize(),
        "jobs_total": job_manager.jobs_total,
        "uptime": str(uptime_td),
        "start_time": start_time.isoformat() + "Z",  # ISO8601 format (UTC)
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
