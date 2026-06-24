from __future__ import annotations

import logging
from typing import Any, Dict, List

import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential

from ..config import settings

logger = logging.getLogger(__name__)


class LocalReranker:
    """
    Cross-encoder reranker using bge-reranker-v2-m3 served by HuggingFace TEI.
    Evaluates each (query, chunk) pair independently — more accurate than cosine.

    Apply only to top-20 candidates (too slow for larger sets).
    Falls back to input order if the reranker is unavailable.
    """

    def __init__(self, url: str = settings.reranker_url):
        self.url = url.rstrip("/")

    async def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_k: int = settings.default_top_k,
    ) -> List[Dict[str, Any]]:
        """
        Rerank candidates using cross-encoder scores.
        Returns top_k results sorted by reranker score.
        """
        if not candidates:
            return []

        texts = [
            c.get("payload", {}).get("content", c.get("result", {}).get("content", ""))
            for c in candidates
        ]
        # Filter empty texts
        valid = [(i, t) for i, t in enumerate(texts) if t.strip()]
        if not valid:
            return candidates[:top_k]

        try:
            scores = await self._call_reranker(query, [t for _, t in valid])
        except Exception as exc:
            logger.warning("[reranker] Unavailable, returning unranked: %s", exc)
            return candidates[:top_k]

        # Map scores back to candidates
        scored = []
        for (orig_idx, _), score in zip(valid, scores):
            candidate = {**candidates[orig_idx], "reranker_score": float(score)}
            scored.append(candidate)

        # Add candidates that had empty text at the bottom
        valid_idxs = {i for i, _ in valid}
        for i, c in enumerate(candidates):
            if i not in valid_idxs:
                scored.append({**c, "reranker_score": -999.0})

        scored.sort(key=lambda x: x["reranker_score"], reverse=True)
        return scored[:top_k]

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=0.5, max=5))
    async def _call_reranker(self, query: str, texts: List[str]) -> List[float]:
        """POST to TEI /rerank endpoint."""
        payload = {
            "query": query,
            "texts": texts,
            "truncate": True,
        }
        async with aiohttp.ClientSession() as session:
            resp = await session.post(
                f"{self.url}/rerank",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            )
            resp.raise_for_status()
            data = await resp.json()
            # TEI returns [{"index": i, "score": f}, …] sorted by index
            data.sort(key=lambda x: x["index"])
            return [item["score"] for item in data]
