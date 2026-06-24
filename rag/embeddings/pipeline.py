from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import AsyncIterator, List, Optional, Tuple

import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential
from tqdm import tqdm

from ..chunking.models import CodeChunk
from ..config import settings

logger = logging.getLogger(__name__)


class EmbeddingPipeline:
    """
    Batch embedding pipeline.
    - Uses fastembed locally when EMBEDDING_MODEL_URL is empty (dev/offline).
    - Switches to a remote TEI HTTP server when the URL is set (production).

    All chunks get their embedding_model and indexed_at fields set here.
    """

    def __init__(
        self,
        model_name: str = settings.embedding_model_name,
        model_version: str = settings.embedding_model_version,
        model_url: str = settings.embedding_model_url,
        batch_size: int = settings.embedding_batch_size,
        max_concurrent: int = settings.embedding_max_concurrent,
    ):
        self.model_name = model_name
        self.model_version = model_version
        self.model_url = model_url.rstrip("/")
        self.batch_size = batch_size
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._local_model = None   # lazy-loaded fastembed model

        if self.model_url:
            logger.info("[embed] Mode: remote TEI → %s", self.model_url)
        else:
            logger.info("[embed] Mode: local fastembed (%s)", self.model_name)

    # ── Public API ────────────────────────────────────────────────────────────

    async def embed_chunks(
        self, chunks: List[CodeChunk], show_progress: bool = True
    ) -> List[Tuple[CodeChunk, List[float]]]:
        """Embed all chunks and return (chunk, vector) pairs."""
        now = datetime.now(timezone.utc).isoformat()
        for chunk in chunks:
            chunk.embedding_model = self.model_name
            chunk.embedding_model_version = self.model_version
            chunk.indexed_at = now

        texts = [c.content for c in chunks]
        vectors = await self._embed_all(texts, show_progress=show_progress)
        return list(zip(chunks, vectors))

    async def embed_single(self, text: str) -> List[float]:
        """Embed a single text — used by retrieval and semantic cache."""
        results = await self._embed_all([text], show_progress=False)
        return results[0]

    # ── Routing ───────────────────────────────────────────────────────────────

    async def _embed_all(
        self, texts: List[str], show_progress: bool = True
    ) -> List[List[float]]:
        if self.model_url:
            return await self._embed_remote(texts, show_progress)
        return self._embed_local(texts, show_progress)

    # ── Local fastembed ───────────────────────────────────────────────────────

    def _embed_local(
        self, texts: List[str], show_progress: bool = True
    ) -> List[List[float]]:
        if self._local_model is None:
            self._local_model = self._load_fastembed()

        all_vectors: List[List[float]] = []
        batches = _batchify(texts, self.batch_size)
        it = tqdm(batches, desc="Embedding (local)", disable=not show_progress)
        for batch in it:
            vectors = list(self._local_model.embed(batch))
            all_vectors.extend([v.tolist() for v in vectors])
        return all_vectors

    def _load_fastembed(self):
        try:
            from fastembed import TextEmbedding
            logger.info("[embed] Loading fastembed model '%s'…", self.model_name)
            return TextEmbedding(model_name=self.model_name)
        except ImportError:
            raise RuntimeError(
                "fastembed not installed. Run: pip install fastembed"
            )

    # ── Remote TEI ────────────────────────────────────────────────────────────

    async def _embed_remote(
        self, texts: List[str], show_progress: bool = True
    ) -> List[List[float]]:
        all_vectors: List[List[float]] = []
        batches = _batchify(texts, self.batch_size)
        it = tqdm(batches, desc="Embedding (remote)", disable=not show_progress)
        for batch in it:
            vectors = await self._embed_batch_remote(batch)
            all_vectors.extend(vectors)
        return all_vectors

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def _embed_batch_remote(self, texts: List[str]) -> List[List[float]]:
        async with self._semaphore:
            async with aiohttp.ClientSession() as session:
                resp = await session.post(
                    f"{self.model_url}/embed",
                    json={"inputs": texts},
                    timeout=aiohttp.ClientTimeout(total=60),
                )
                resp.raise_for_status()
                data = await resp.json()
                # TEI returns {"embeddings": [[…], …]}
                return data.get("embeddings", data)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _batchify(items: list, size: int) -> list[list]:
    return [items[i: i + size] for i in range(0, len(items), size)]
