# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# System deps for pygit2 + tree-sitter compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libgit2-dev \
    pkg-config \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Security: run as non-root
RUN groupadd -r raguser && useradd -r -g raguser raguser

WORKDIR /app

# Runtime system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgit2-1.5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Optional: install gitleaks for secret scanning
# Download from GitHub releases; pin the version for reproducibility.
ARG GITLEAKS_VERSION=8.18.4
RUN curl -sSfL \
    "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" \
    | tar -xz -C /usr/local/bin gitleaks \
    && chmod +x /usr/local/bin/gitleaks \
    || echo "gitleaks download failed — regex-only secret scanning will be used"

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY rag/ /app/rag/

# Ownership
RUN chown -R raguser:raguser /app

USER raguser

# ── Healthcheck ────────────────────────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

# ── Entrypoint ────────────────────────────────────────────────────────────────
CMD ["python", "-m", "uvicorn", "rag.api.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--log-level", "info"]
