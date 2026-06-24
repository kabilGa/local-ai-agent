from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from rank_bm25 import BM25Okapi

from ..config import settings
from ..embeddings.pipeline import EmbeddingPipeline
from ..storage.qdrant_store import QdrantStore
from .query_preprocessor import QueryPreprocessor

logger = logging.getLogger(__name__)


class HybridSearcher:
    """
    Three-signal hybrid retrieval:
      1. Dense search  (cosine similarity on embeddings)
      2. Sparse search (BM25 on tokenised chunk content)
      3. Symbol graph  (exact identifier match on calls/names)

    Signals are fused with Reciprocal Rank Fusion (RRF).
    RBAC pre-filter is MANDATORY and applied before every Qdrant call.
    """

    def __init__(
        self,
        store: QdrantStore,
        embedder: EmbeddingPipeline,
        bm25_index: Optional["BM25Index"] = None,
        symbol_graph=None,
    ):
        self.store = store
        self.embedder = embedder
        self.bm25_index = bm25_index
        self.symbol_graph = symbol_graph
        self.preprocessor = QueryPreprocessor()

    async def search(
        self,
        query: str,
        project_id: str,
        allowed_roles: List[str],
        top_k: int = settings.default_top_k,
        filters: Optional[Dict[str, Any]] = None,
        use_hyde: bool = False,
        model_gateway=None,
    ) -> List[Dict[str, Any]]:
        """
        Execute hybrid retrieval and return top_k fused results.
        RBAC is enforced at the Qdrant layer — never bypassed.
        """
        processed = self.preprocessor.preprocess(query)

        # Optional HyDE
        if use_hyde and model_gateway:
            processed["hypothetical_snippet"] = QueryPreprocessor.generate_hyde(
                query, model_gateway
            )

        search_text = processed["hypothetical_snippet"] or processed["normalised"]

        # Signal 1 — Dense
        query_vector = await self.embedder.embed_single(search_text)
        dense_results = self.store.dense_search(
            query_vector=query_vector,
            project_id=project_id,
            allowed_roles=allowed_roles,
            top_k=settings.reranker_top_k,
            score_threshold=settings.score_threshold,
        )

        # Signal 2 — BM25 Sparse
        sparse_results: List[Dict] = []
        if self.bm25_index and processed["keywords"]:
            sparse_results = self.bm25_index.search(
                keywords=processed["keywords"],
                project_id=project_id,
                allowed_roles=allowed_roles,
                top_k=settings.reranker_top_k,
            )

        # Signal 3 — Symbol graph
        graph_results: List[Dict] = []
        if self.symbol_graph and processed["keywords"]:
            for kw in processed["keywords"]:
                matches = self.symbol_graph.search_by_name(kw)
                for fqn in matches[:5]:
                    graph_results.append({"id": fqn, "score": 1.0, "payload": {"node_name": fqn}})

        # RRF fusion
        fused = _rrf_fusion(
            [
                _normalise_results(dense_results, "dense"),
                _normalise_results(sparse_results, "sparse"),
                graph_results,
            ],
            k=settings.rrf_k,
        )

        return fused[:top_k]


# ── BM25 Index ────────────────────────────────────────────────────────────────

class BM25Index:
    """
    In-memory BM25 index over indexed chunks.
    Rebuilt after each full indexation.
    Only serves chunks the requesting user is allowed to see.
    """

    def __init__(self) -> None:
        self._docs: List[Dict[str, Any]] = []     # [{id, payload, tokens}]
        self._bm25: BM25Okapi | None = None

    def build(self, chunks_payloads: List[Dict[str, Any]]) -> None:
        """Build index from a list of chunk payload dicts."""
        self._docs = []
        corpus = []
        for payload in chunks_payloads:
            tokens = _tokenize(payload.get("content", ""))
            self._docs.append({
                "id": payload.get("chunk_id", ""),
                "payload": payload,
                "tokens": tokens,
            })
            corpus.append(tokens)

        if corpus:
            self._bm25 = BM25Okapi(corpus)
        logger.info("[bm25] Index built with %d documents", len(self._docs))

    def search(
        self,
        keywords: List[str],
        project_id: str,
        allowed_roles: List[str],
        top_k: int = 20,
    ) -> List[Dict[str, Any]]:
        if self._bm25 is None or not self._docs:
            return []

        scores = self._bm25.get_scores(keywords)
        ranked = sorted(
            enumerate(scores), key=lambda x: x[1], reverse=True
        )

        results = []
        for idx, score in ranked[:top_k * 3]:   # over-fetch then RBAC-filter
            if score <= 0:
                break
            doc = self._docs[idx]
            payload = doc["payload"]

            # RBAC check
            if payload.get("project_id") != project_id:
                continue
            doc_roles = payload.get("allowed_roles", [])
            if not any(r in doc_roles for r in allowed_roles):
                continue

            results.append({"id": doc["id"], "score": float(score), "payload": payload})
            if len(results) >= top_k:
                break

        return results


# ── RRF Fusion ────────────────────────────────────────────────────────────────

def _rrf_fusion(result_lists: List[List[Dict]], k: int = 60) -> List[Dict]:
    """
    Reciprocal Rank Fusion: score = Σ 1 / (k + rank_i).
    Combines multiple ranked lists into a single ranking.
    """
    fused: Dict[str, Dict] = {}

    for result_list in result_lists:
        for rank, item in enumerate(result_list):
            item_id = str(item.get("id", ""))
            if not item_id:
                continue
            if item_id not in fused:
                fused[item_id] = {"id": item_id, "rrf_score": 0.0, "result": item}
            fused[item_id]["rrf_score"] += 1.0 / (k + rank + 1)

    return sorted(fused.values(), key=lambda x: x["rrf_score"], reverse=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalise_results(results: List[Any], source: str) -> List[Dict]:
    """Convert Qdrant ScoredPoint objects or plain dicts to a uniform format."""
    normalised = []
    for r in results:
        if hasattr(r, "id"):
            # Qdrant ScoredPoint
            normalised.append({
                "id": str(r.id),
                "score": float(r.score),
                "payload": r.payload or {},
                "source": source,
            })
        elif isinstance(r, dict):
            normalised.append({**r, "source": source})
    return normalised


def _tokenize(text: str) -> List[str]:
    """Simple whitespace + camelCase tokeniser for BM25."""
    import re
    # Split on non-alphanumeric boundaries + camelCase boundaries
    tokens = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text)
    # Expand camelCase: getUserById → ["get", "user", "by", "id"]
    expanded = []
    for token in tokens:
        parts = re.sub(r"([A-Z])", r" \1", token).split()
        expanded.extend(p.lower() for p in parts if len(p) > 1)
    return expanded
