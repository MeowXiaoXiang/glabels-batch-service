<!-- .github/copilot-instructions.md
Guidance for AI coding agents working on this repo.
Keep concise, actionable, and project-specific.
-->

# Agent Guide — glabels-batch-service

## Project Overview

FastAPI microservice wrapping gLabels CLI: **JSON → CSV → gLabels Template → PDF**.

Core flow: `app/main.py` → `JobManager` → `LabelPrintService` → `GlabelsEngine`

**Version**: see `app/core/version.py` (`VERSION`, `SERVICE_NAME` = `gLabels Batch Service`)

## Key Files

| File | Role |
|------|------|
| `app/main.py` | FastAPI app, lifespan manages JobManager, system endpoints |
| `app/services/job_manager.py` | In-memory job store, asyncio queue, worker pool |
| `app/services/label_print.py` | JSON→CSV, batch splitting, PDF merging |
| `app/utils/glabels_engine.py` | Async subprocess wrapper for `glabels-3-batch` |
| `app/utils/cpu_detect.py` | Container-aware CPU count (cgroup v2/v1 → os.cpu_count) |
| `app/services/template_service.py` | Template discovery, format detection |
| `app/parsers/__init__.py` | Parser factory (`get_parser()`) |
| `app/parsers/base_parser.py` | Abstract base class for template parsers |
| `app/parsers/csv_parser.py` | CSV format parser (header/no-header) |
| `app/schema.py` | Pydantic models and validation |
| `app/api/print_jobs.py` | All `/labels/*` endpoints |
| `app/config.py` | pydantic-settings, all env vars |
| `app/core/limiter.py` | Shared SlowAPI rate limiter instance |
| `app/core/logger.py` | loguru logging setup |

## Architecture & Conventions

### Job Lifecycle

- Jobs stored in memory (`JobManager.jobs`); no persistence layer.
- Retention cleanup is time-based (`RETENTION_HOURS`).
- Cleanup triggers: (1) startup, (2) after each job completes, (3) hourly via `_cleanup_scheduler`.

### Concurrency (two layers)

- `JobManager.max_parallel` — controls worker count
- `GlabelsEngine` — semaphore for subprocess concurrency
- Keep both in sync when modifying parallelism.

### Parser Architecture

- Factory pattern: `get_parser(format_type)` → returns `BaseParser` subclass
- Currently only `CSVParser` (supports header and no-header CSV)
- `TemplateService._detect_format` parses gzipped `.glabels` XML to choose parser
- To add a new parser: subclass `BaseParser`, add case to `get_parser()` match

### File Locations

| Directory | Purpose | Notes |
|-----------|---------|-------|
| `templates/` | Read-only templates | `.glabels` files |
| `output/` | Generated PDFs | `{template}_{timestamp}.pdf` |
| `temp/` | Intermediate CSV | Retained only when `KEEP_CSV=true` |
| `logs/` | Log files | Configurable via `LOG_DIR` |

Do not hardcode absolute paths; always use these relative directories.

## API Endpoints Reference

### System (in `app/main.py`)

- `GET /` — API root info (service, version, uptime, docs links)
- `GET /health` — health check

### Labels (in `app/api/print_jobs.py`, prefix `/labels`)

- `POST /labels/print` — submit print job
- `GET /labels/jobs` — list recent jobs (with `limit` param)
- `GET /labels/jobs/{job_id}` — get job status
- `GET /labels/jobs/{job_id}/stream` — SSE real-time status
- `GET /labels/jobs/{job_id}/download` — download PDF (404/409/410)
- `GET /labels/templates` — list all templates with fields
- `GET /labels/templates/{template_name}` — specific template info

## Environment Variables

All defined in `app/config.py`:

| Variable | Description | Default |
|----------|-------------|---------|
| `ENVIRONMENT` | `development` / `production` (production blocks `RELOAD=true`) | `production` |
| `HOST` / `PORT` | Server bind address | `0.0.0.0` / `8000` |
| `RELOAD` | Auto-reload on code changes (dev only) | `false` |
| `KEEP_CSV` | Retain temp CSV files for debugging | `false` |
| `MAX_PARALLEL` | Worker count (0 = auto, cgroup-aware) | `0` |
| `MAX_LABELS_PER_BATCH` | Labels per batch before auto-split and merge | `300` |
| `MAX_LABELS_PER_JOB` | Max labels per request | `2000` |
| `GLABELS_TIMEOUT` | **Per-batch** subprocess timeout in seconds | `600` |
| `RETENTION_HOURS` | Job retention before cleanup | `24` |
| `MAX_REQUEST_BYTES` | Request body size cap (bytes) | `5000000` |
| `MAX_FIELDS_PER_LABEL` | Max fields per label record | `50` |
| `MAX_FIELD_LENGTH` | Max length per field value | `2048` |
| `LOG_LEVEL` | DEBUG / INFO / WARNING / ERROR | `INFO` |
| `LOG_FORMAT` | Logging format (text/json) | `text` |
| `LOG_DIR` | Log file directory | `logs` |
| `REQUEST_ID_HEADER` | Request ID header name | `X-Request-ID` |
| `RATE_LIMIT` | Rate limit for `/labels/print` | `60/minute` |
| `ENABLE_METRICS` | Enable Prometheus `/metrics` endpoint | `true` |
| `SHUTDOWN_TIMEOUT` | Graceful shutdown queue drain timeout (seconds) | `30` |
| `CORS_ALLOW_ORIGINS` | Comma-separated allowed origins (empty = disabled) | `` |

## Developer Workflows

```bash
# Local dev (Linux/WSL2)
cp .env.example .env
pip install -r requirements.txt
sudo apt-get install glabels glabels-data
python -m app.main

# Docker (recommended)
docker compose up -d

# Tests (no gLabels binary needed)
pytest tests/ -v

# VS Code: press F5 (uses .vscode/launch.json)
```

## Test Suite (71 tests)

| File | Tests | Focus |
|------|-------|-------|
| `test_glabels_engine.py` | 7 | Subprocess mock: success, failure, timeout |
| `test_job_manager.py` | 8 | Job lifecycle, workers, cleanup |
| `test_template_service.py` | 7 | Template discovery and parsing |
| `test_label_print.py` | 16 | CSV generation, batching, PDF merging |
| `test_api_endpoints.py` | 17 | API validation, error responses |
| `test_cpu_detect.py` | 12 | cgroup v2/v1 parsing, fallback to os |
| `test_integration.py` | 4 | End-to-end workflows |

## Patterns & Gotchas

### Exception Types (preserve these)

- `GlabelsRunError` — base class
- `GlabelsTimeoutError` — per-batch timeout exceeded
- `GlabelsExecutionError` — non-zero exit code
- `FileNotFoundError` — template or output missing

### Test Mocking

- Tests monkeypatch `asyncio.create_subprocess_exec` and `jm.service.generate_pdf`
- When changing `GlabelsEngine.run_batch` or JobManager worker semantics, update tests

### Template Validation

- Filenames must end with `.glabels`
- Enforced in `LabelRequest` model and `TemplateService._resolve_template_path`

### Logging

- Uses `loguru` with custom setup in `app/core/logger.py`
- Keep log message structure consistent for test assertions

## Safety Rules for AI Edits

1. **Do not change** public API routes or JSON model fields without updating `app/schema.py` and OpenAPI examples in `app/api/print_jobs.py`.
2. **Preserve** exception classes and error messages used in tests.
3. **Keep** default directories and env-driven flags.
4. **Validate** that `ENVIRONMENT=production` + `RELOAD=true` is blocked (see `config.py:model_post_init`).

## Common Implementation Patterns

**Add a new endpoint that enqueues a job:**
Mimic `app/api/print_jobs.py:submit_labels` — validate `LabelRequest`, call `job_manager.submit_job(req)`, return `JobSubmitResponse`.

**Call glabels with extra args:**
Use `LabelPrintService.generate_pdf(..., copies=n)` which passes `extra_args=["--copies=n"]` to `GlabelsEngine.run_batch`.

**Add a new parser:**
1. Create `app/parsers/new_parser.py`, subclass `BaseParser`
2. Implement `parse_template_info()`
3. Add case to `get_parser()` in `app/parsers/__init__.py`
4. Update `TemplateService._detect_format` to detect the new format
