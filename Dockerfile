# Default production runtime: GTK. Qt is available in the opt-in qt-test stage.
FROM python:3.14.8-slim-bookworm@sha256:48b13b003dda20b16f9442b8475aa05fe21bf6579a8c881db92ffb4d8fd20f83 AS runtime
ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    glabels glabels-data fonts-dejavu fonts-noto-cjk curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt constraints-linux.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c constraints-linux.txt && pip check
COPY app ./app
COPY templates ./templates
RUN mkdir -p output temp state logs && glabels-3-batch --help >/dev/null
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/ready || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--limit-concurrency", "128", "--timeout-graceful-shutdown", "5"]

FROM runtime AS test
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils zbar-tools \
    && rm -rf /var/lib/apt/lists/*
COPY requirements-dev.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements-dev.txt -c constraints-linux.txt && pip check
COPY tests ./tests
CMD ["pytest", "--cov-report=xml"]

FROM test AS qt-test
ARG GLABELS_QT_REV=37901c153cf7f3abffe4e9355e00755d2b152b5b
RUN apt-get update && apt-get install -y --no-install-recommends \
    git cmake ninja-build g++ pkg-config qt6-base-dev qt6-svg-dev \
    qt6-tools-dev qt6-tools-dev-tools zlib1g-dev libqrencode-dev \
    && rm -rf /var/lib/apt/lists/*
RUN git init /opt/glabels-qt \
    && git -C /opt/glabels-qt remote add origin https://github.com/j-evins/glabels-qt.git \
    && git -C /opt/glabels-qt fetch --depth=1 origin "$GLABELS_QT_REV" \
    && git -C /opt/glabels-qt checkout --detach FETCH_HEAD \
    && cmake -S /opt/glabels-qt -B /opt/qt-build -G Ninja -DCMAKE_BUILD_TYPE=Release \
    && cmake --build /opt/qt-build --target glabels-batch-qt -j 2 \
    && cp /opt/qt-build/glabels-batch/glabels-batch-qt /usr/local/bin/
ENV QT_QPA_PLATFORM=offscreen

# Keep a plain build focused on the default GTK runtime.
FROM runtime AS production
