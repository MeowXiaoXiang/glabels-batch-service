# gLabels Batch Service

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.128.6-009688?logo=fastapi&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)
![Linux](https://img.shields.io/badge/Platform-Linux-FCC624?logo=linux&logoColor=black)
![pytest](https://img.shields.io/badge/tests-pytest-0A9EDC?logo=pytest)
![MIT License](https://img.shields.io/badge/License-MIT-green.svg)

A **FastAPI** microservice for batch label printing using **gLabels**. Converts **JSON → CSV → gLabels Template → PDF** with async job processing, parallel execution, and timeout handling.

**[中文版本 README](README_tw.md)**

---

## Features

- **Batch Processing**: Convert JSON data to PDF labels in batches
- **Async Job Queue**: Background task processing with worker pool
- **Real-time Status**: Server-Sent Events (SSE) for live progress updates
- **Auto-Batching**: Automatically splits large jobs and merges PDFs
- **Template Management**: Auto-discovery and parsing of `.glabels` templates
- **Production Ready**: Docker support, health checks, configurable limits

---

## Quick Start

```bash
# 1. Copy environment template
cp .env.example .env

# 2. Start service (docker compose reads .env)
docker compose up -d

# 3. Open API docs
http://localhost:8000/docs
```

---

## Installation

### Docker (Recommended)

**Development (with hot reload):**

```bash
docker compose up -d
```

Notes:

- `compose.yml` only loads `.env` and does not override values. Update `.env` to change settings like `LOG_FORMAT`.
- Missing `.env` will fail to start the container. Copy from `.env.example` first.

**Production:**

```bash
docker compose -f compose.prod.yml up -d
```

### Native Installation (Linux/WSL only)

```bash
# Install gLabels
sudo apt-get install glabels glabels-data fonts-dejavu fonts-noto-cjk

# Install Python dependencies
pip install -r requirements.txt

# Run
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

> **Windows users**: gLabels requires Linux. Use Docker or WSL2.

---

## Production Deployment

### Using Docker Compose (Recommended)

```bash
# Set environment variables
export ENVIRONMENT=production
export LOG_LEVEL=WARNING
export MAX_PARALLEL=4

# Start service
docker compose -f compose.prod.yml up -d
```

### Using Docker Run

```bash
docker build -t glabels-batch-service:latest .

docker run -d \
  --name glabels-batch-service \
  -p 8000:8000 \
  -e ENVIRONMENT=production \
  -e RELOAD=false \
  -e LOG_LEVEL=WARNING \
  -v /data/output:/app/output \
  -v /data/templates:/app/templates \
  -v /data/logs:/app/logs \
  --restart always \
  glabels-batch-service:latest
```

### Production Checklist

- [ ] `ENVIRONMENT=production`
- [ ] `RELOAD=false` (critical - validation will fail if true)
- [ ] `LOG_LEVEL=WARNING` or `ERROR`
- [ ] Volume mounts configured properly
- [ ] Health monitoring on `/health` endpoint
- [ ] Resource limits set
- [ ] Never commit `.env.production` to git

### Using with nginx (Reverse Proxy)

If deploying behind nginx, configure the following for proper SSE support:

```nginx
upstream backend {
    server 127.0.0.1:8000;
    keepalive 32;
}

server {
    listen 80;
    server_name example.com;

    # SSE endpoints (real-time streaming)
    location /labels/jobs/ {
        proxy_pass http://backend;
        proxy_http_version 1.1;
        
        # Disable buffering for Server-Sent Events
        proxy_buffering off;
        proxy_cache off;
        
        # Keep connection open for long-lived requests
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        
        # Required headers
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
        
        # CORS (optional, if needed)
        add_header Access-Control-Allow-Origin * always;
    }

    # All other endpoints (normal buffering)
    location / {
        proxy_pass http://backend;
        proxy_http_version 1.1;
        
        proxy_buffering on;
        proxy_read_timeout 60s;
        
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
    }
}
```

**Key Configuration Points**:

- `proxy_buffering off` — Required for SSE to work properly
- `proxy_read_timeout 3600s` — Allow up to 1 hour for long-running jobs
- `proxy_http_version 1.1` — Essential for connection reuse
- `Connection ""` — Prevents nginx from adding `Connection: close`

> **Tip**: If using SSL/TLS, ensure `proxy_set_header X-Forwarded-Proto $scheme;` is set so the app knows it's behind HTTPS.

> **Linux hosts**: The container runs as UID 1000. Ensure mounted directories are writable:
>
> ```bash
> sudo chown -R 1000:1000 ./output ./logs ./templates
> ```
>
> Docker Desktop (Windows/Mac) handles permissions automatically — no action needed.

---

## Configuration

### Environment Variables

Copy `.env.example` to `.env` and adjust:

| Variable | Description | Default |
|----------|-------------|---------|
| `ENVIRONMENT` | Runtime environment (development/production) | `production` |
| `HOST` / `PORT` | Server address and port | `0.0.0.0` / `8000` |
| `RELOAD` | Auto-reload on code changes (dev only) | `false` |
| `MAX_PARALLEL` | Parallel workers (0=auto, cgroup-aware) | `0` |
| `MAX_LABELS_PER_BATCH` | Labels per batch before split | `300` |
| `MAX_LABELS_PER_JOB` | Max labels per request | `2000` |
| `GLABELS_TIMEOUT` | Timeout per batch in seconds | `600` |
| `RETENTION_HOURS` | Job retention time | `24` |
| `LOG_LEVEL` | Logging level (DEBUG/INFO/WARNING/ERROR) | `INFO` |
| `LOG_FORMAT` | Logging format (text/json) | `text` |
| `LOG_DIR` | Log file directory | `logs` |
| `REQUEST_ID_HEADER` | Request ID header name | `X-Request-ID` |
| `RATE_LIMIT` | Rate limit for `/labels/print` | `60/minute` |
| `ENABLE_METRICS` | Enable Prometheus metrics endpoint | `true` |
| `SHUTDOWN_TIMEOUT` | Graceful shutdown timeout (seconds) | `30` |
| `KEEP_CSV` | Retain intermediate CSV files | `false` |
| `MAX_REQUEST_BYTES` | Request body size limit | `5000000` |
| `MAX_FIELDS_PER_LABEL` | Max fields per label record | `50` |
| `MAX_FIELD_LENGTH` | Max length per field value | `2048` |
| `CORS_ALLOW_ORIGINS` | Comma-separated allowed origins (empty=disabled) | `` |

### Configuration Priority

1. Default values in `app/config.py`
2. `.env` file (development)
3. System environment variables (production - recommended)

### Environment Files

| File | Purpose | Commit? |
|------|---------|---------|
| `.env.example` | Development template | Yes |
| `.env.production.example` | Production template | Yes |
| `.env` | Development config | No |
| `.env.production` | Production config | No |

> **Security**: Never commit `.env` or `.env.production` to version control.

---

## API Examples

### Submit Print Job

```bash
curl -X POST http://localhost:8000/labels/print \
  -H "Content-Type: application/json" \
  -d '{
    "template_name": "demo.glabels",
    "data": [
      {"CODE": "A001", "ITEM": "Product A"},
      {"CODE": "A002", "ITEM": "Product B"}
    ],
    "copies": 1
  }'
```

**Response:**

```json
{"job_id": "abc123..."}
```

### Check Job Status

```bash
curl http://localhost:8000/labels/jobs/{job_id}
```

**Response Example:**

```json
{
  "job_id": "abc123...",
  "status": "done",
  "template": "demo.glabels",
  "filename": "demo_20260209_103000.pdf",
  "error": null,
  "created_at": "2026-02-09T10:30:00",
  "started_at": "2026-02-09T10:30:01",
  "finished_at": "2026-02-09T10:30:05"
}
```

### Stream Status (SSE)

Real-time status updates using Server-Sent Events:

```bash
curl -N http://localhost:8000/labels/jobs/{job_id}/stream
```

**JavaScript Example:**

```javascript
const es = new EventSource('/labels/jobs/{job_id}/stream');
es.addEventListener('status', (e) => {
    const job = JSON.parse(e.data);
    console.log(job.status);  // pending → running → done
    if (job.status === 'done' || job.status === 'failed') {
        es.close();
    }
});
```

### Download PDF

```bash
# Download file
curl -O http://localhost:8000/labels/jobs/{job_id}/download

# Preview in browser
curl http://localhost:8000/labels/jobs/{job_id}/download?preview=true
```

### List Templates

```bash
curl http://localhost:8000/labels/templates
```

**Response Example:**

```json
[
  {
    "name": "demo.glabels",
    "field_count": 2,
    "has_headers": true
  }
]
```

---

## Templates & Data Format

### Template Files

- Place `.glabels` template files in `templates/` directory
- System automatically discovers and parses field definitions
- Use `/labels/templates` API to view available templates and fields

### Data Format Requirements

- JSON field names must match template variables exactly (case-sensitive)
- `data` array must not be empty
- Maximum `MAX_LABELS_PER_JOB` labels per request (default 2000)
- Maximum `MAX_FIELDS_PER_LABEL` fields per label record (default 50)
- Maximum `MAX_FIELD_LENGTH` characters per field value (default 2048)

### File Output

- Generated PDFs saved to `output/` directory
- Filename format: `{template_name}_{timestamp}.pdf`
- Temporary CSV files in `temp/` (retained if `KEEP_CSV=true`)
- Jobs retained for `RETENTION_HOURS` hours after completion (default 24)

---

## Observability

### Request ID

Every response includes an `X-Request-ID` header. Pass your own in the request or let the server generate one. Use it to trace a request through logs.

### Rate Limiting

`/labels/print` is rate-limited (default `60/minute`). Exceeding the limit returns `429 Too Many Requests`. Adjust via `RATE_LIMIT` env var.

### Prometheus Metrics

When `ENABLE_METRICS=true` (default), a `/metrics` endpoint exposes request counts, latency histograms, and status codes in Prometheus format.

```bash
curl http://localhost:8000/metrics
```

### Graceful Shutdown

On shutdown the service waits up to `SHUTDOWN_TIMEOUT` seconds (default 30) for running jobs to finish before stopping workers.

---

## Architecture

### Execution Flow

```text
Client Request → FastAPI → JobManager → LabelPrintService → GlabelsEngine → PDF Output
                               ↓              ↓                  ↓
                           Queue Mgmt     JSON→CSV           CLI Wrapper
                           Worker Pool    Batch Split        subprocess
                                          PDF Merge
```

### Project Structure

```text
app/
├── api/
│   └── print_jobs.py          # API routes and endpoints
├── core/
│   ├── limiter.py             # Rate limiter instance (SlowAPI)
│   ├── logger.py              # Logging configuration
│   └── version.py             # Version info
├── parsers/
│   ├── base_parser.py         # Base parser class
│   └── csv_parser.py          # CSV format parser
├── services/
│   ├── job_manager.py         # Job queue and worker management
│   ├── label_print.py         # JSON→CSV, batch split, PDF merge
│   └── template_service.py    # Template discovery and parsing
├── utils/
│   ├── cpu_detect.py          # Container-aware CPU detection (cgroup)
│   └── glabels_engine.py      # glabels-3-batch CLI wrapper
├── config.py                  # Environment configuration (pydantic-settings)
├── schema.py                  # Pydantic data models
└── main.py                    # FastAPI application entry point
```

### Key Components

- **JobManager**: Manages job queue, worker pool, status tracking, and cleanup
- **LabelPrintService**: Handles JSON to CSV conversion, batch splitting, PDF merging
- **GlabelsEngine**: Async wrapper for `glabels-3-batch` CLI with timeout handling
- **TemplateService**: Auto-discovers `templates/` directory and parses `.glabels` files

---

## Testing

```bash
# Run all tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=app --cov-report=html

# View coverage report
open htmlcov/index.html

# Specific test file
pytest tests/test_glabels_engine.py -v
```

---

## Troubleshooting

**Common Issues:**

| Issue | Solution |
|-------|----------|
| `404 Job not found` | Job expired (default 24h retention) or invalid job_id |
| `409 Conflict` | Job still running, wait for completion |
| `410 Gone` | Job expired and cleaned up |
| `glabels-3-batch not found` | Use Docker (gLabels auto-installed) |
| Template not found | Verify `.glabels` file exists in `templates/` directory |
| Timeout errors | `GLABELS_TIMEOUT` is **per-batch** timeout (default 600s). 1000 labels = 4 batches = up to 2400s total |
| Windows compatibility | Use Docker Desktop or WSL2 (gLabels requires Linux) |

**Frequently Asked Questions:**

**Q: How to handle large label batches?**  
A: System automatically splits batches (default 300 labels/batch) and merges PDFs. Adjust `MAX_LABELS_PER_BATCH` as needed.

**Q: How to adjust parallel processing?**  
A: Set `MAX_PARALLEL` - `0` for auto (CPU-1), or specify explicit number like `4`. Production: match CPU cores.

**Q: Job stuck in pending status?**  
A: Check `docker compose logs -f` to verify workers are running. Verify `MAX_PARALLEL` setting.

**Debugging:**

```bash
# View container logs
docker compose logs -f

# Check container status
docker compose ps

# Access container shell
docker compose exec glabels-batch-service sh

# Check health status
curl http://localhost:8000/health

# View runtime info
curl http://localhost:8000/
```

---

## Development

### Local Setup

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Install gLabels (Linux/WSL)
sudo apt-get install glabels glabels-data fonts-dejavu fonts-noto-cjk

# Run service (with hot reload)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Or press F5 in VS Code for debugging (uses .env)
```

### Code Quality

```bash
# Run linter
ruff check app/ tests/

# Format code
ruff format app/ tests/

# Type checking
mypy app/
```
