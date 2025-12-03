# Python 3.12 (Debian Bookworm slim)
FROM python:3.12-slim-bookworm

# Prevent interactive APT prompts
ENV DEBIAN_FRONTEND=noninteractive

# Python runtime optimizations
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install gLabels CLI + basic fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    glabels \
    glabels-data \
    fonts-dejavu \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*
    
# Verify CLI is available
RUN glabels-3-batch --help > /dev/null

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

EXPOSE 8000

# Entrypoint
CMD ["python", "-m", "app.main"]
