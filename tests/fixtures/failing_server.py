"""Subprocess-only fault injection; never shipped in the runtime image."""

import asyncio
import sqlite3
import sys
from pathlib import Path

import app.main as main
from app.config import Settings
from app.utils.glabels_renderer import GlabelsRenderer


async def blocked_renderer(self, **kwargs):
    await asyncio.sleep(60)


def launch() -> None:
    root = Path(sys.argv[1])
    main.settings = Settings(
        _env_file=None,
        HOST="127.0.0.1",
        PORT=int(sys.argv[2]),
        GLABELS_EXECUTABLE=sys.executable,
        MAX_INFLIGHT_JOBS=1,
        MAX_PENDING_JOBS=4,
        SHUTDOWN_TIMEOUT=0.05,
        MIN_FREE_DISK_BYTES=0,
        TEMPLATES_DIR=root / "templates",
        STATE_DIR=root / "state",
        OUTPUT_DIR=root / "output",
        TEMP_DIR=root / "temp",
        LOG_DIR=str(root / "logs"),
    )
    GlabelsRenderer.run_batch = blocked_renderer
    create_app = main.create_app

    def with_fault_route(cfg, **kwargs):
        app = create_app(cfg, **kwargs)

        @app.post("/test/write-fault")
        async def fail():
            jobs = app.state.job_manager
            await jobs.store._io(
                lambda: jobs.store.db.set_authorizer(
                    lambda action, *args: (
                        sqlite3.SQLITE_DENY
                        if action == sqlite3.SQLITE_INSERT
                        else sqlite3.SQLITE_OK
                    )
                )
            )
            return {"armed": True}

        return app

    main.create_app = with_fault_route
    main.run()


if __name__ == "__main__":
    launch()
