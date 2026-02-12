# Python 3.12 (Debian Bookworm slim)
FROM python:3.12-slim-bookworm

# Prevent interactive APT prompts
ENV DEBIAN_FRONTEND=noninteractive

# Python runtime optimizations
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install gLabels CLI + basic fonts + curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    glabels \
    glabels-data \
    fonts-dejavu \
    fonts-noto-cjk \
    curl \
    && rm -rf /var/lib/apt/lists/*
    
# Verify CLI is available
RUN glabels-3-batch --help > /dev/null

WORKDIR /app

# Install Python deps (optimize layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code and templates
COPY ./app ./app
COPY ./templates ./templates

# Create runtime directories
RUN mkdir -p /app/output /app/temp /app/logs

EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Entrypoint: use uvicorn command
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
