"""FastAPI lifespan owns exactly one local coordinator and persistent store."""

import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from loguru import logger
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Histogram,
    generate_latest,
)
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, Metric
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app import SERVICE_NAME, VERSION
from app.api.print_jobs import router
from app.config import Settings, settings
from app.core.body_limit import BodyLimitMiddleware
from app.core.limiter import limiter
from app.core.logger import setup_logger
from app.services.job_manager import JobManager


def create_app(cfg: Settings | None = None) -> FastAPI:
    cfg = cfg or settings

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        setup_logger(cfg.LOG_LEVEL, cfg.LOG_FORMAT, cfg.LOG_DIR)
        jobs = JobManager(cfg)
        application.state.job_manager = jobs
        application.state.start_time = datetime.now(UTC)
        await jobs.start()
        try:
            yield
        finally:
            try:
                await jobs.stop()
            finally:
                logger.remove()

    application = FastAPI(
        title=SERVICE_NAME,
        version=VERSION,
        lifespan=lifespan,
        description="Opaque-template GTK/Qt batch rendering with persistent short-term downloads",
    )
    application.state.settings = cfg
    application.state.limiter = limiter
    application.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
    application.add_middleware(
        BodyLimitMiddleware,
        max_bytes=cfg.MAX_REQUEST_BYTES,
        max_admissions=cfg.MAX_PENDING_JOBS + cfg.MAX_INFLIGHT_JOBS,
    )
    if cfg.CORS_ALLOW_ORIGINS:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=[
                x.strip() for x in cfg.CORS_ALLOW_ORIGINS.split(",") if x.strip()
            ],
            allow_methods=["*"],
            allow_headers=["*"],
            allow_credentials=False,
        )
    registry = CollectorRegistry()
    latency = Histogram(
        "http_request_duration_seconds",
        "Time to response headers",
        ["method", "route", "status"],
        registry=registry,
    )

    class JobMetrics:
        def collect(self) -> Iterable[Metric]:
            jobs = getattr(application.state, "job_manager", None)
            if jobs is None:
                return
            for name, value in {
                "submitted": jobs.submitted,
                "completed": jobs.completed,
                "failed": jobs.failed,
                "worker_restarts": jobs.merger.restarts,
                "cleanup_failures": jobs.cleanup_failures,
            }.items():
                yield CounterMetricFamily(
                    "jobs_" + name, name.replace("_", " "), value=value
                )
            values = jobs.scheduler.snapshot() | {
                "pending": len(jobs.pending),
                "inflight": len(jobs.active),
                "workspace_bytes": sum(jobs.pipeline.workspace_bytes.values()),
            }
            for name, value in values.items():
                yield GaugeMetricFamily(
                    "jobs_" + name, name.replace("_", " "), value=value
                )
            for name, stage_values in (
                ("wait", jobs.scheduler.wait_seconds),
                ("run", jobs.scheduler.run_seconds),
            ):
                family = CounterMetricFamily(
                    "jobs_work_" + name + "_seconds",
                    "Work lease " + name + " seconds",
                    labels=["stage"],
                )
                for stage, value in stage_values.items():
                    family.add_metric([stage], value)
                yield family

    registry.register(JobMetrics())

    @application.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        identifier = (request.headers.get(cfg.REQUEST_ID_HEADER) or uuid4().hex)[:128]
        request.state.request_id = identifier
        started = time.monotonic()
        with logger.contextualize(request_id=identifier):
            response = await call_next(request)
        response.headers[cfg.REQUEST_ID_HEADER] = identifier
        route = getattr(request.scope.get("route"), "path", "unmatched")
        if cfg.ENABLE_METRICS:
            latency.labels(request.method, route, str(response.status_code)).observe(
                time.monotonic() - started
            )
        return response

    @application.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.opt(exception=exc).error("Unhandled request failure")
        return JSONResponse(
            {"detail": "Internal Server Error"},
            500,
            headers={cfg.REQUEST_ID_HEADER: getattr(request.state, "request_id", "-")},
        )

    @application.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/ready", tags=["system"])
    async def ready(request: Request) -> JSONResponse:
        jobs: JobManager = request.app.state.job_manager
        return JSONResponse({"ready": jobs.ready}, 200 if jobs.ready else 503)

    @application.get("/", tags=["system"])
    async def root(request: Request) -> dict[str, Any]:
        return {
            "service": SERVICE_NAME,
            "version": VERSION,
            "start_time": request.app.state.start_time.isoformat(),
            "docs": "/docs",
        }

    if cfg.ENABLE_METRICS:

        @application.get("/metrics", include_in_schema=False)
        async def metrics() -> Response:
            return Response(
                generate_latest(registry), headers={"Content-Type": CONTENT_TYPE_LATEST}
            )

    application.include_router(router)
    return application


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.RELOAD,
        limit_concurrency=128,
    )
