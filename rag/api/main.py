from __future__ import annotations

import logging
import logging.config
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..cache.semantic_cache import SemanticCache
from ..config import settings
from ..embeddings.pipeline import EmbeddingPipeline
from ..indexing.incremental import IncrementalIndexer
from ..indexing.indexer import Indexer
from ..retrieval.context_assembler import ContextAssembler
from ..retrieval.hybrid_searcher import HybridSearcher
from ..retrieval.reranker import LocalReranker
from ..storage.qdrant_store import QdrantStore
from .routes import health, index, retrieve

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


# ── Lifespan — initialise / teardown shared resources ─────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("═══════════════════════════════════════════")
    logger.info("  RAG Engine  —  starting up")
    logger.info("═══════════════════════════════════════════")

    # ── Storage ───────────────────────────────────────────────────────────────
    store = QdrantStore(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        dim=settings.embedding_dim,
    )
    app.state.store = store

    # ── Embedder ──────────────────────────────────────────────────────────────
    embedder = EmbeddingPipeline(
        model_name=settings.embedding_model_name,
        model_version=settings.embedding_model_version,
        model_url=settings.embedding_model_url,
        batch_size=settings.embedding_batch_size,
        max_concurrent=settings.embedding_max_concurrent,
    )
    app.state.embedder = embedder

    # ── Reranker ──────────────────────────────────────────────────────────────
    reranker = LocalReranker(url=settings.reranker_url)
    app.state.reranker = reranker

    # ── Semantic cache ────────────────────────────────────────────────────────
    cache = SemanticCache(
        redis_url=settings.redis_url,
        ttl=settings.cache_ttl_seconds,
        threshold=settings.cache_similarity_threshold,
        enabled=settings.cache_enabled,
    )
    app.state.cache = cache

    # ── Symbol graph (loaded from Redis if available) ─────────────────────────
    symbol_graph = None
    try:
        import redis as _redis
        r = _redis.from_url(settings.redis_url)
        from ..chunking.symbol_graph import SymbolGraph
        symbol_graph = SymbolGraph.load_from_redis(r, "global")
        if symbol_graph:
            logger.info("Symbol graph loaded from Redis (%d nodes)", len(symbol_graph))
    except Exception as exc:
        logger.debug("Symbol graph not available: %s", exc)

    # ── Searcher ──────────────────────────────────────────────────────────────
    searcher = HybridSearcher(
        store=store,
        embedder=embedder,
        symbol_graph=symbol_graph,
    )
    app.state.searcher = searcher

    # ── Context assembler ─────────────────────────────────────────────────────
    assembler = ContextAssembler(
        max_context_tokens=settings.max_context_tokens,
        symbol_graph=symbol_graph,
    )
    app.state.assembler = assembler

    # ── Indexer ───────────────────────────────────────────────────────────────
    indexer = Indexer(store=store, embedder=embedder)
    app.state.indexer = indexer

    # ── Incremental indexer + webhook worker ──────────────────────────────────
    incremental = IncrementalIndexer(store=store, embedder=embedder)
    await incremental.start_worker()
    app.state.incremental_indexer = incremental

    logger.info("All components initialised — ready to serve")
    logger.info("═══════════════════════════════════════════")

    yield   # ── App is running ─────────────────────────────────────────────────

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("Shutting down RAG Engine…")
    await incremental.stop_worker()
    logger.info("Shutdown complete")


# ── App ───────────────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title="RAG Engine — Code Search API",
        description=(
            "Local RAG engine for the AI coding/debugging/security agent.\n\n"
            "All retrieval is RBAC-filtered by project and role. "
            "No data leaves the local environment."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # ── CORS (adjust origins for production) ──────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://localhost:8080"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routes ────────────────────────────────────────────────────────────────
    app.include_router(retrieve.router, prefix="/v1",   tags=["retrieval"])
    app.include_router(index.router,    prefix="/v1/index", tags=["indexing"])
    app.include_router(health.router,                   tags=["ops"])

    return app


app = create_app()


# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "rag.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
        log_level=settings.log_level.lower(),
    )
