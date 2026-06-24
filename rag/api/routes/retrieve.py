from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request

from ...api.schemas import RetrieveRequest, RetrieveResponse, SourceReference
from ...cache.semantic_cache import SemanticCache
from ...metrics.prometheus import (
    CACHE_HITS,
    CACHE_MISSES,
    RETRIEVAL_CHUNKS_RETURNED,
    RETRIEVAL_LATENCY,
    RETRIEVAL_REQUESTS,
)
from ...retrieval.context_assembler import ContextAssembler
from ...retrieval.hybrid_searcher import HybridSearcher
from ...retrieval.reranker import LocalReranker
from ...config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


def get_searcher(request: Request) -> HybridSearcher:
    return request.app.state.searcher


def get_cache(request: Request) -> SemanticCache:
    return request.app.state.cache


def get_reranker(request: Request) -> LocalReranker:
    return request.app.state.reranker


def get_assembler(request: Request) -> ContextAssembler:
    return request.app.state.assembler


@router.post(
    "/retrieve",
    response_model=RetrieveResponse,
    summary="Retrieve relevant code chunks for a query",
    description=(
        "Performs hybrid semantic + BM25 + symbol-graph retrieval "
        "with mandatory RBAC pre-filtering. Returns assembled context "
        "and exact source references."
    ),
)
async def retrieve(
    body: RetrieveRequest,
    searcher: HybridSearcher = Depends(get_searcher),
    cache: SemanticCache = Depends(get_cache),
    reranker: LocalReranker = Depends(get_reranker),
    assembler: ContextAssembler = Depends(get_assembler),
) -> RetrieveResponse:
    t0 = time.monotonic()
    cache_hit = False

    # Only single-project queries for now (multi-project is roadmap)
    if len(body.project_ids) > 1:
        raise HTTPException(
            status_code=422,
            detail="Multi-project retrieval not yet supported. Pass exactly one project_id.",
        )
    project_id = body.project_ids[0]

    options = body.options or {}
    use_reranker = options.get("use_reranker", settings.reranker_enabled)
    use_hyde = options.get("use_hyde", False)

    try:
        # ── 1. Semantic cache lookup ───────────────────────────────────────────
        query_embedding = await searcher.embedder.embed_single(body.query)

        cached = await cache.get(
            query=body.query,
            query_embedding=query_embedding,
            user_id=body.user_id,
            project_ids=body.project_ids,
        )
        if cached is not None:
            cache_hit = True
            CACHE_HITS.inc()
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            RETRIEVAL_LATENCY.labels(cache_hit="true").observe(time.monotonic() - t0)
            RETRIEVAL_REQUESTS.labels(status="success", cache_hit="true").inc()
            return RetrieveResponse(
                query=body.query,
                assembled_context=cached.get("assembled_context", ""),
                sources=[SourceReference(**s) for s in cached.get("sources", [])],
                retrieval_time_ms=elapsed_ms,
                cache_hit=True,
                chunks_found=cached.get("chunks_found", 0),
                injection_detected=cached.get("injection_detected", False),
            )

        CACHE_MISSES.inc()

        # ── 2. Hybrid retrieval ────────────────────────────────────────────────
        results = await searcher.search(
            query=body.query,
            project_id=project_id,
            allowed_roles=body.allowed_roles,
            top_k=body.top_k,
            filters=body.filters,
            use_hyde=use_hyde,
        )

        # ── 3. Optional reranking ──────────────────────────────────────────────
        if use_reranker and results:
            results = await reranker.rerank(
                query=body.query,
                candidates=results,
                top_k=body.top_k,
            )

        # ── 4. Context assembly + anti-injection ───────────────────────────────
        context = assembler.assemble(
            query=body.query,
            ranked_results=results,
            include_callers=options.get("include_symbol_graph", True),
        )

        sources = [SourceReference(**s) for s in context["sources"]]
        RETRIEVAL_CHUNKS_RETURNED.observe(len(sources))

        # ── 5. Cache store ────────────────────────────────────────────────────
        cache_payload = {
            "assembled_context": context["assembled_context"],
            "sources": [s.model_dump() for s in sources],
            "chunks_found": len(results),
            "injection_detected": context.get("injection_detected", False),
            "project_ids": body.project_ids,
        }
        await cache.set(
            query=body.query,
            query_embedding=query_embedding,
            user_id=body.user_id,
            project_ids=body.project_ids,
            result=cache_payload,
        )

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        RETRIEVAL_LATENCY.labels(cache_hit="false").observe(time.monotonic() - t0)
        RETRIEVAL_REQUESTS.labels(status="success", cache_hit="false").inc()

        return RetrieveResponse(
            query=body.query,
            assembled_context=context["assembled_context"],
            sources=sources,
            retrieval_time_ms=elapsed_ms,
            cache_hit=False,
            chunks_found=len(results),
            injection_detected=context.get("injection_detected", False),
        )

    except HTTPException:
        raise
    except Exception as exc:
        RETRIEVAL_REQUESTS.labels(status="error", cache_hit="false").inc()
        logger.error("[retrieve] Unexpected error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Retrieval failed. Check server logs.")
