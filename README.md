# Labels Service

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.118.0-009688?logo=fastapi&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)
![Linux](https://img.shields.io/badge/Platform-Linux-FCC624?logo=linux&logoColor=black)
![pytest](https://img.shields.io/badge/tests-pytest-0A9EDC?logo=pytest)
![MIT License](https://img.shields.io/badge/License-MIT-green.svg)

A **FastAPI** microservice that provides REST API for label printing by integrating with **gLabels**.  
Converts **JSON → CSV → gLabels Template → PDF** with async job processing, parallel execution, timeout handling, and file downloads.

📖 **[中文版本 README](README_tw.md)**

## Quick Start

```bash
# 1. Copy environment template
cp .env.example .env

# 2. Start with Docker Compose
docker compose up -d

# 3. Open API docs
open http://localhost:8000/docs
```

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
├── services/      # Business logic (JobManager, TemplateService)
├── utils/         # GlabelsEngine CLI wrapper
├── models/        # Data models and DTOs
├── core/          # Logging and configuration
└── main.py        # FastAPI application entry point
```

## Requirements

- **Linux platform** (gLabels only supports Linux)
- **Windows users**: Use WSL2 or Docker Desktop
- Docker & Docker Compose
- gLabels software (automatically installed in Docker container)

## Docker Setup

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
docker build -t labels-service .

# 2. Create directories (adjust paths as needed)
mkdir -p /path/to/your/output /path/to/your/templates
# mkdir -p /path/to/your/temp  # Only needed if KEEP_CSV=true in .env

# 3. Run container with .env file
docker run -d \
  --name labels-service \
  -p 8000:8000 \
  --env-file .env \
  -v /path/to/your/output:/app/output \
  -v /path/to/your/templates:/app/templates \
  --restart unless-stopped \
  labels-service
  # Add temp volume only if KEEP_CSV=true:
  # -v /path/to/your/temp:/app/temp \
```

#### Method B: With environment parameters

```bash
# 1. Build image
docker build -t labels-service .

# 2. Create directories (adjust paths as needed)
mkdir -p /path/to/your/output /path/to/your/templates
# mkdir -p /path/to/your/temp  # Only needed if KEEP_CSV=true

# 3. Run container with environment variables
docker run -d \
  --name labels-service \
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
  labels-service
  # Add temp volume and set KEEP_CSV=true if you want to retain CSV files:
  # -e KEEP_CSV=true \
  # -v /path/to/your/temp:/app/temp \

# 4. Check logs
docker logs -f labels-service

# 5. Access API docs
open http://localhost:8000/docs
```

**Stop and cleanup:**

```bash
docker stop labels-service
docker rm labels-service
```

## Environment Variables

Copy `.env.example` to `.env` and adjust as needed:

```bash
HOST=0.0.0.0
PORT=8000
RELOAD=false
KEEP_CSV=false
MAX_PARALLEL=0
GLABELS_TIMEOUT=600
RETENTION_HOURS=24
LOG_LEVEL=INFO
```

## Local Development

**Note**: For local development, you need Linux or WSL2 since gLabels only supports Linux platforms.

```bash
# Setup virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install development dependencies (for testing and linting)
pip install -r requirements-dev.txt

# Install gLabels on your Linux system (required dependency)
sudo apt-get install glabels glabels-data

# Run application
python -m app.main
```

### VS Code Debugging (F5)

The project includes `.vscode/launch.json` for debugging. Simply press **F5** to start debugging with breakpoints.

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
curl http://localhost:8000/labels/status/abc123...
```

### Download PDF

```bash
curl -O http://localhost:8000/labels/download/abc123...
```

### List Templates

```bash
curl http://localhost:8000/labels/templates
```

## Templates & Data Format

- Place `.glabels` template files in `templates/` directory
- JSON data fields must match template variables
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
docker compose exec label-service sh
```

## Deployment Notes

- Backup `templates/` and `output/` directories regularly
- Monitor container resource usage
- Logs auto-rotate (5MB/file, keeps 10 files), configurable in `app/core/logger.py`

## Configuration Tips

- `MAX_PARALLEL=0` auto-sets to CPU cores-1, adjust based on system performance
- `GLABELS_TIMEOUT=600` increase if processing large datasets times out
- `KEEP_CSV=true` enables CSV file retention for debugging purposes
- `RETENTION_HOURS=24` controls how long jobs are kept in memory
