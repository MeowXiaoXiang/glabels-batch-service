# Default production runtime: GTK. Qt is available in the opt-in qt-test stage.
FROM ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff AS uv

FROM python:3.14.9-slim-bookworm@sha256:945c2676dc2b18e0c1f16879244122c57c0ffede60006bf3df159c507a31bcae AS runtime
ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    glabels glabels-data fonts-dejavu fonts-noto-cjk curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
# uv is mounted only for installation.
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    uv sync --locked --no-dev --no-cache && uv pip check
COPY app ./app
COPY templates ./templates
RUN mkdir -p output temp state logs && glabels-3-batch --help >/dev/null
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/ready || exit 1
CMD ["python", "-m", "app.main"]

FROM runtime AS test
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils zbar-tools \
    && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /usr/local/bin/uv
RUN uv sync --locked --no-cache && uv pip check
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
