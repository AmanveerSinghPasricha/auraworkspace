# ==========================================
# STAGE 1: Builder Stage (Compile & Build Wheels)
# ==========================================
FROM python:3.13-slim AS builder

WORKDIR /build

# Install C-compilers and development libraries for binary packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install python dependencies into a temporary prefix directory
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --prefix=/build/pip_packages -r requirements.txt


# ==========================================
# STAGE 2: Runtime Stage (Slim Production)
# ==========================================
FROM python:3.13-slim AS runner

WORKDIR /app

# Install minimal runtime libraries required for PostgreSQL driver & document processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    poppler-utils \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

# Copy pre-compiled dependencies from builder
COPY --from=builder /build/pip_packages /usr/local

# Copy application source code
COPY app/ /app/app

# Create persistent directories for uploads and vectorless cache
RUN mkdir -p /app/uploads /app/.vectorless_cache

# Expose FastAPI default port
EXPOSE 8000

# Container healthcheck using FastAPI health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Launch Uvicorn ASGI server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]