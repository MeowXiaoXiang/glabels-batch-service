<!-- .github/copilot-instructions.md
Guidance for AI coding agents working on this repo.
Keep concise, actionable, and project-specific.
-->

# Quick Agent Notes — glabels-batch-service

Short, focused guidance to help an AI coding assistant be productive in this repository.

-   Project purpose: FastAPI microservice that wraps the gLabels CLI to convert JSON → CSV → gLabels → PDF. Core flow: app/main.py → JobManager → LabelPrintService → GlabelsEngine (app/utils/glabels_engine.py).

-   Key files to read first:

    -   `app/main.py` (FastAPI app, lifespan manages JobManager, health/info endpoints)
    -   `app/services/job_manager.py` (in-memory job store, asyncio queue, worker pool, jobs_total counter)
    -   `app/services/label_print.py` (JSON→CSV conversion, temp file policy, output naming)
    -   `app/utils/glabels_engine.py` (async subprocess wrapper for `glabels-3-batch`)
    -   `app/services/template_service.py` and `app/parsers/*` (template discovery and parsing)
    -   `app/schema.py` (Pydantic schema models and validation rules)
    -   `app/api/print_jobs.py` (all `/labels/*` endpoints)
    -   `app/config.py` (pydantic-settings, all env vars)
    -   `app/core/version.py` (VERSION and SERVICE_NAME constants)

-   Architecture & conventions (what to preserve):

    -   Jobs are stored in memory (`JobManager.jobs`); retention cleanup is time-based (`RETENTION_HOURS`). Cleanup runs: (1) at startup, (2) after each job completes, (3) every hour via `_cleanup_scheduler`. Avoid changing this semantics unless adding persistence.
    -   Concurrency is controlled in two layers: `JobManager.max_parallel` controls worker count; `GlabelsEngine` uses a semaphore for subprocess concurrency. Keep both in sync when modifying parallelism.
    -   File locations: `templates/` (read-only templates), `output/` (PDFs), `temp/` (optional CSV retention when `KEEP_CSV=true`), `logs/` (configurable via `LOG_DIR`). Do not hardcode absolute paths; use these relative directories.
-   Template filenames must end with `.glabels`. Validation is enforced in `LabelRequest` model and `TemplateService._resolve_template_path`.

-   API endpoints reference:

    -   System endpoints (in `app/main.py`):
        -   `GET /` — API root info (service name, version, docs links)
        -   `GET /health` — lightweight health check
        -   `GET /info` — runtime info (uptime, workers, queue_size, jobs_total)
    -   Label endpoints (in `app/api/print_jobs.py`, prefix `/labels`):
        -   `POST /labels/print` — submit print job
        -   `GET /labels/jobs` — list recent jobs (with limit param)
        -   `GET /labels/jobs/{job_id}` — get job status
        -   `GET /labels/jobs/{job_id}/stream` — SSE stream for real-time status updates
        -   `GET /labels/jobs/{job_id}/download` — download PDF (returns 404/409/410)
        -   `GET /labels/templates` — list all templates with field info
        -   `GET /labels/templates/{template_name}` — get specific template info

-   Environment variables (all in `app/config.py`):

    -   `HOST`, `PORT`, `RELOAD` — server config
    -   `KEEP_CSV` — retain temp CSV files for debugging
    -   `MAX_PARALLEL` — worker count (0 = auto)
-   `MAX_LABELS_PER_BATCH` — max labels per batch before auto-split and merge (default: 300)
-   `MAX_LABELS_PER_JOB` — max labels per request (default: 2000)
-   `GLABELS_TIMEOUT` — subprocess timeout in seconds
-   `RETENTION_HOURS` — job retention before cleanup
-   `MAX_REQUEST_BYTES` — request body size cap (bytes)
-   `MAX_FIELDS_PER_LABEL` — max fields per label record
-   `MAX_FIELD_LENGTH` — max length per field value
-   `LOG_LEVEL` — logging verbosity
-   `LOG_DIR` — log file directory (default: `logs`)
-   `CORS_ALLOW_ORIGINS` — comma-separated allowed origins (empty disables CORS)

-   Developer workflows & useful commands (verified in README):

    -   Local dev (Linux/WSL2):
        -   Copy env: `cp .env.example .env`
        -   Install deps: `pip install -r requirements.txt`
        -   Install gLabels: `sudo apt-get install glabels glabels-data`
        -   Run app: `python -m app.main`
    -   Docker (recommended): see `README.md` — `docker compose up -d` after copying `.env`.
    -   Tests: `pytest tests/` (unit tests mock subprocesses; running tests doesn't require gLabels binary).
    -   VS Code debugging: Press F5 (uses `.vscode/launch.json`).

-   Patterns and gotchas for edits and PRs:

    -   Tests frequently monkeypatch `asyncio.create_subprocess_exec` and `jm.service.generate_pdf`. When changing `GlabelsEngine.run_batch` or JobManager worker semantics, update tests accordingly.
    -   `GlabelsEngine.run_batch` raises typed errors: base class `GlabelsRunError`, and subclasses `GlabelsTimeoutError`, `GlabelsExecutionError`, plus `FileNotFoundError`. Preserve those exception types for callers to handle.
    -   `LabelPrintService._json_to_csv` relies on field ordering inferred by key appearance. If you change CSV behavior, update `tests/test_job_manager.py` and `tests/test_glabels_engine.py`.
    -   Logging uses `loguru` and a custom setup in `app/core/logger.py` — keep log messages' structure for consistency with tests and troubleshooting.

-   Test files overview:

    -   `tests/test_api_endpoints.py` — API validation tests
    -   `tests/test_job_manager.py` — job submission, worker, cleanup tests
    -   `tests/test_glabels_engine.py` — subprocess mock tests (success, failure, timeout)
    -   `tests/test_label_print.py` — batch splitting, PDF merging, utility functions tests
    -   `tests/test_template_service.py` — template discovery and parsing tests
    -   `tests/test_integration.py` — end-to-end workflow tests

-   Small examples to follow when implementing changes:

    -   To add a new endpoint that enqueues a job, mimic `app/api/print_jobs.py:submit_labels` — validate `LabelRequest`, call `job_manager.submit_job(req)`, return `JobSubmitResponse`.
    -   To call glabels with extra args, use `LabelPrintService.generate_pdf(..., copies=n)` which passes `extra_args=["--copies=n"]` to `GlabelsEngine.run_batch`.

-   Where to look for integration points:

    -   Background workers lifecycle: `app.main:lifespan` starts/stops `JobManager` and workers.
    -   Template detection: `TemplateService._detect_format` parses gzipped `.glabels` XML and chooses parser type in `app/parsers`.

-   Safety & backward-compatibility rules for AI edits:
    1. Do not change public API routes or JSON model fields without updating `app/schema.py` and OpenAPI examples in `app/api/print_jobs.py`.
    2. Preserve exception classes and error messages used in tests (`Glabels*` errors and HTTP 404/409/410 cases).
    3. Keep default directories (`templates/`, `output/`, `temp/`, `logs/`) and env-driven flags (`KEEP_CSV`, `MAX_PARALLEL`, `MAX_LABELS_PER_BATCH`, `GLABELS_TIMEOUT`, `LOG_DIR`).

If anything above is unclear or you want more examples (e.g., common PR templates or how to mock subprocesses in tests), tell me which area to expand.
