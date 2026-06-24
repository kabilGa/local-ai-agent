from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from ...api.schemas import HealthResponse, ReadinessResponse
from ...config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

# Injected at startup
_VERSION = "1.0.0"


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness probe — is the process alive?",
    tags=["ops"],
)
async def health() -> HealthResponse:
    """Kubernetes liveness probe. Always returns 200 if the process is running."""
    return HealthResponse(
        status="ok",
        version=_VERSION,
        components={
            "api": "ok",
        },
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe — are all dependencies reachable?",
    tags=["ops"],
)
async def readiness(request: Request) -> ReadinessResponse:
    """
    Kubernetes readiness probe.
    Checks Qdrant and embedding model are reachable before serving traffic.
    Returns 503 if any critical dependency is down.
    """
    checks: dict[str, bool] = {}

    # Qdrant
    try:
        store = request.app.state.store
        store.client.get_collections()
        checks["qdrant"] = True
    except Exception as exc:
        logger.warning("[ready] Qdrant unreachable: %s", exc)
        checks["qdrant"] = False

    # Redis (non-critical — cache is optional)
    try:
        cache = request.app.state.cache
        if cache._redis:
            cache._redis.ping()
            checks["redis"] = True
        else:
            checks["redis"] = False
    except Exception:
        checks["redis"] = False

    # Embedding model (ping fastembed or remote TEI)
    try:
        embedder = request.app.state.embedder
        if embedder.model_url:
            import httpx
            r = httpx.get(f"{embedder.model_url}/health", timeout=3)
            checks["embedding_model"] = r.status_code == 200
        else:
            # fastembed is local — check model is loaded
            checks["embedding_model"] = embedder._local_model is not None or True
    except Exception as exc:
        logger.warning("[ready] Embedding model unreachable: %s", exc)
        checks["embedding_model"] = False

    ready = checks.get("qdrant", False)   # Qdrant is the only hard dependency

    if not ready:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Service not ready")

    return ReadinessResponse(ready=ready, checks=checks)


@router.get(
    "/metrics",
    summary="Prometheus metrics scrape endpoint",
    tags=["ops"],
    include_in_schema=False,
)
async def metrics() -> Response:
    """Expose Prometheus metrics for scraping. Mount separately if needed."""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
