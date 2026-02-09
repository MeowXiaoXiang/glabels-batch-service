# gLabels Batch Service

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.119.0-009688?logo=fastapi&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)
![Linux](https://img.shields.io/badge/Platform-Linux-FCC624?logo=linux&logoColor=black)
![pytest](https://img.shields.io/badge/tests-pytest-0A9EDC?logo=pytest)
![MIT License](https://img.shields.io/badge/License-MIT-green.svg)

A **FastAPI** microservice that provides REST API for label printing by integrating with **gLabels**.  
Converts **JSON → CSV → gLabels Template → PDF** with async job processing, parallel execution, timeout handling, and file downloads.

**[中文版本 README](README_tw.md)**

## Quick Start

```bash
# 1. Copy environment template
cp .env.example .env

# 2. Start with Docker Compose
docker compose up -d

# 3. Open API docs
open http://localhost:8000/docs
```

## Quick Start (Development)

### Option 1: Native Development (Linux/Mac/WSL)

**Requirements:**
- Python 3.12
- Linux or WSL2 (gLabels only supports Linux)

```bash
# 1. Copy environment template
cp .env.example .env

# 2. Setup virtual environment
python -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# 4. Install gLabels
sudo apt-get install glabels glabels-data fonts-dejavu fonts-noto-cjk

# 5. Run with uvicorn (auto-reload enabled)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Or press F5 in VS Code for debugging
```

### Option 2: Docker Development (Windows/Cross-platform)

```bash
# 1. Copy environment template
cp .env.example .env

# 2. Start with Docker Compose (hot reload enabled)
docker compose up -d

# 3. View logs
docker compose logs -f

# 4. Open API docs
open http://localhost:8000/docs
```

The development setup includes:
- Hot reload on code changes (via `--reload` flag or mounted ./app directory)
- Debug-level logging
- CSV file retention for debugging

---

## Production Deployment

### Method 1: Using Environment Variables (Recommended)

Set environment variables in your deployment platform (Kubernetes, AWS ECS, etc.):

```bash
# Build image
docker build -t glabels-batch-service:latest .

# Run with environment variables
docker run -d \
  --name glabels-batch-service \
  -p 8000:8000 \
  -e ENVIRONMENT=production \
  -e RELOAD=false \
  -e LOG_LEVEL=WARNING \
  -e KEEP_CSV=false \
  -e MAX_PARALLEL=4 \
  -v /data/output:/app/output \
  -v /data/templates:/app/templates \
  -v /data/logs:/app/logs \
  --restart always \
  glabels-batch-service:latest
```

### Method 2: Using compose.prod.yml

```bash
# 1. Set environment variables in your system or CI/CD
export ENVIRONMENT=production
export LOG_LEVEL=WARNING
export MAX_PARALLEL=4
# ... other settings

# 2. Start production service
docker compose -f compose.prod.yml up -d

# 3. Check status
docker compose -f compose.prod.yml ps
docker compose -f compose.prod.yml logs -f
```

### Production Checklist

Before deploying to production, ensure:

- [ ] `ENVIRONMENT=production` is set
- [ ] `RELOAD=false` (CRITICAL - will fail validation if true)
- [ ] `LOG_LEVEL` set to WARNING or ERROR
- [ ] `KEEP_CSV=false` (saves disk space)
- [ ] Set `MAX_PARALLEL` based on available CPU cores
- [ ] Configure proper volume mounts for `/app/output`, `/app/templates`, `/app/logs`
- [ ] Set up monitoring for `/health` endpoint
- [ ] Configure resource limits (CPU/memory)
- [ ] Use secrets management for sensitive configuration
- [ ] **Never commit .env.production to git** - use system environment variables instead

---

## Configuration Priority

Configuration is loaded in the following order (later overrides earlier):

1. **Default values** in `app/config.py`
2. **`.env` file** (if it exists) - used in development
3. **System environment variables** - recommended for production

Example:
```bash
# .env file has: LOG_LEVEL=DEBUG
# System env has: export LOG_LEVEL=WARNING
# Result: LOG_LEVEL=WARNING (system env wins)
```

---

## Environment Files

| File | Purpose | Commit to Git? |
|------|---------|----------------|
| `.env.example` | Development template | ✅ Yes |
| `.env.production.example` | Production template | ✅ Yes |
| `.env` | Development configuration | ❌ No |
| `.env.production` | Production configuration | ❌ No |
| `.env.local` | Local overrides | ❌ No |

---

## Security Notice

**Important:** Never commit environment files with real values (`.env`, `.env.production`) to version control.

- `.env.example` and `.env.production.example` are safe templates
- `compose.prod.yml` uses `${VAR:-default}` syntax to load from system environment
- For production, prefer system environment variables over `.env` files
- The application validates that `RELOAD=false` in production mode

---

## Architecture

```text
Client Request → FastAPI → JobManager → TemplateService → GlabelsEngine → PDF Output
                              ↓              ↓              ↓
                         Async Queue    Template Discovery  CLI Wrapper
```

## Project Structure

```text
app/
├── api/           # API routes and endpoints
├── core/          # Logging and version info
├── parsers/       # Template format parsers
├── services/      # Business logic (JobManager, TemplateService)
├── utils/         # GlabelsEngine CLI wrapper
├── config.py      # Environment configuration
├── schema.py      # Pydantic schema models
└── main.py        # FastAPI application entry point
```

## Requirements

- **Linux platform** (gLabels only supports Linux)
- **Windows users**: Use WSL2 or Docker Desktop
- Docker & Docker Compose
- gLabels software (automatically installed in Docker container)

## Docker Setup (Alternative Methods)

**Note:** For quick start, see the sections above. This section provides alternative Docker deployment methods.

### Option 1: Docker Compose (Recommended)

```bash
# 1. Copy environment template
cp .env.example .env

# 2. Build and start
docker compose up -d

# 3. Check status
docker compose ps
docker compose logs -f

# 4. Access API docs
open http://localhost:8000/docs
```

### Option 2: Pure Dockerfile

#### Method A: With .env file

```bash
# 1. Copy environment template and build image
cp .env.example .env
docker build -t glabels-batch-service .

# 2. Create directories (adjust paths as needed)
mkdir -p /path/to/your/output /path/to/your/templates
# mkdir -p /path/to/your/temp  # Only needed if KEEP_CSV=true in .env

# 3. Run container with .env file
docker run -d \
  --name glabels-batch-service \
  -p 8000:8000 \
  --env-file .env \
  -v /path/to/your/output:/app/output \
  -v /path/to/your/templates:/app/templates \
  --restart unless-stopped \
  glabels-batch-service
  # Add temp volume only if KEEP_CSV=true:
  # -v /path/to/your/temp:/app/temp \
```

#### Method B: With environment parameters

```bash
# 1. Build image
docker build -t glabels-batch-service .

# 2. Create directories (adjust paths as needed)
mkdir -p /path/to/your/output /path/to/your/templates
# mkdir -p /path/to/your/temp  # Only needed if KEEP_CSV=true

# 3. Run container with environment variables
docker run -d \
  --name glabels-batch-service \
  -p 8000:8000 \
  -e HOST=0.0.0.0 \
  -e PORT=8000 \
  -e LOG_LEVEL=INFO \
  -e KEEP_CSV=false \
  -e MAX_PARALLEL=0 \
  -e GLABELS_TIMEOUT=600 \
  -e RETENTION_HOURS=24 \
  -v /path/to/your/output:/app/output \
  -v /path/to/your/templates:/app/templates \
  --restart unless-stopped \
  glabels-batch-service
  # Add temp volume and set KEEP_CSV=true if you want to retain CSV files:
  # -e KEEP_CSV=true \
  # -v /path/to/your/temp:/app/temp \

# 4. Check logs
docker logs -f glabels-batch-service

# 5. Access API docs
open http://localhost:8000/docs
```

**Stop and cleanup:**

```bash
docker stop glabels-batch-service
docker rm glabels-batch-service
```

## Environment Variables

Copy `.env.example` to `.env` and adjust as needed:

```bash
HOST=0.0.0.0
PORT=8000
RELOAD=false
KEEP_CSV=false
MAX_PARALLEL=0
MAX_LABELS_PER_BATCH=300
MAX_LABELS_PER_JOB=2000
GLABELS_TIMEOUT=600
RETENTION_HOURS=24
LOG_LEVEL=INFO
MAX_REQUEST_BYTES=5000000
MAX_FIELDS_PER_LABEL=50
MAX_FIELD_LENGTH=2048
CORS_ALLOW_ORIGINS=
```

## Local Development

See the **[Quick Start (Development)](#quick-start-development)** section above for detailed local development setup instructions.

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

Response:

```json
{"job_id": "abc123..."}
```

### Check Job Status

```bash
curl http://localhost:8000/labels/jobs/abc123...
```

### Stream Job Status (SSE)

For real-time status updates, use Server-Sent Events:

```bash
curl -N http://localhost:8000/labels/jobs/abc123.../stream
```

Or in JavaScript:

```javascript
const es = new EventSource('/labels/jobs/abc123.../stream');
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
curl -O http://localhost:8000/labels/jobs/abc123.../download
```

Preview in browser:

```bash
curl http://localhost:8000/labels/jobs/abc123.../download?preview=true
```

### List Templates

```bash
curl http://localhost:8000/labels/templates
```

## Templates & Data Format

- Place `.glabels` template files in `templates/` directory
- JSON data fields must match template variables
- Data array must be non-empty and within configured limits
- Generated PDFs saved to `output/` directory
- Temporary CSV files in `temp/` (configurable retention)

## Testing

```bash
# Run all tests
pytest tests/

# Run with verbose output
pytest tests/ -v

# Run with coverage report
pytest tests/ --cov=app --cov-report=html

# Run specific test
pytest tests/test_glabels_engine.py
```

## Troubleshooting

**Common Issues:**

- `404 Job not found` - Job expired or doesn't exist
- `glabels-3-batch not found` - gLabels not installed (shouldn't happen in Docker)
- Permission errors - Check volume mount permissions
- Template not found - Verify template exists in `templates/` directory
- **Windows compatibility** - Use Docker Desktop or WSL2 (gLabels requires Linux)

**Debugging:**

```bash
# Check container logs
docker compose logs -f

# Check container status
docker compose ps

# Access container shell
docker compose exec glabels-batch-service sh
```

## Deployment Notes

- Backup `templates/` and `output/` directories regularly
- Monitor container resource usage
- Logs auto-rotate (5MB/file, keeps 10 files), configurable in `app/core/logger.py`

## Configuration Tips

- `MAX_PARALLEL=0` auto-sets to CPU cores-1, adjust based on system performance
- `MAX_LABELS_PER_BATCH=300` controls how many labels are processed per batch before merging into a single PDF
- `MAX_LABELS_PER_JOB=2000` limits labels per request to avoid oversized jobs
- `MAX_REQUEST_BYTES=5000000` caps request body size to protect memory usage
- `MAX_FIELDS_PER_LABEL=50` limits the number of fields per label record
- `MAX_FIELD_LENGTH=2048` limits the length of any single field value
- `CORS_ALLOW_ORIGINS` comma-separated allowed origins (leave empty to disable CORS)
- `GLABELS_TIMEOUT=600` increase if processing large datasets times out
- `KEEP_CSV=true` enables CSV file retention for debugging purposes
- `RETENTION_HOURS=24` controls how long jobs are kept in memory
