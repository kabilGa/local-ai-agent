from __future__ import annotations

import logging
from typing import List, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    HnswConfigDiff,
    MatchAny,
    MatchValue,
    PointStruct,
    ScalarQuantization,
    ScalarQuantizationConfig,
    ScalarType,
    VectorParams,
)

from ..chunking.models import CodeChunk
from ..config import settings

logger = logging.getLogger(__name__)

# ── Collection naming ─────────────────────────────────────────────────────────

def collection_name(project_id: str, model_version: str = settings.embedding_model_version) -> str:
    """
    One collection per project × model version (isolation maximale — CDC §4.2).
    Format: {project_id}__{model_version}
    """
    safe_version = model_version.replace(".", "-").replace("/", "-")
    return f"{project_id}__{safe_version}"


# ── QdrantStore ───────────────────────────────────────────────────────────────

class QdrantStore:
    """
    Thin wrapper around QdrantClient with:
    - Per-project collection isolation
    - INT8 scalar quantization
    - HNSW index tuned for code retrieval
    - Atomic upsert and delete operations

    Compatible with qdrant-client >= 1.10 (uses query_points instead of the
    deprecated search() method).
    """

    def __init__(
        self,
        url: str = settings.qdrant_url,
        api_key: str = settings.qdrant_api_key,
        dim: int = settings.embedding_dim,
    ):
        self.dim = dim
        self.client = QdrantClient(url=url, api_key=api_key, timeout=30)
        logger.info("[qdrant] Connected to %s", url)

    # ── Collection lifecycle ──────────────────────────────────────────────────

    def ensure_collection(self, project_id: str, model_version: Optional[str] = None) -> str:
        """Create collection if it doesn't exist. Return collection name."""
        version = model_version or settings.embedding_model_version
        name = collection_name(project_id, version)

        existing = {c.name for c in self.client.get_collections().collections}
        if name not in existing:
            self.client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(
                    size=self.dim,
                    distance=Distance.COSINE,
                    hnsw_config=HnswConfigDiff(m=16, ef_construct=200),
                ),
                quantization_config=ScalarQuantization(
                    scalar=ScalarQuantizationConfig(
                        type=ScalarType.INT8,
                        quantile=0.99,
                        always_ram=True,
                    )
                ),
            )
            logger.info("[qdrant] Created collection '%s'", name)

            # Create payload indexes for RBAC filtering (mandatory)
            self._create_indexes(name)

        return name

    def _create_indexes(self, name: str) -> None:
        """Create payload field indexes required for RBAC and filtering."""
        fields = [
            ("project_id", "keyword"),
            ("tenant_id", "keyword"),
            ("allowed_roles", "keyword"),
            ("file_path", "keyword"),
            ("language", "keyword"),
            ("node_type", "keyword"),
            ("branch", "keyword"),
            ("sensitivity_level", "keyword"),
        ]
        for field, schema_type in fields:
            try:
                self.client.create_payload_index(
                    collection_name=name,
                    field_name=field,
                    field_schema=schema_type,
                )
            except Exception as exc:
                logger.debug("[qdrant] Index '%s' may already exist: %s", field, exc)

    def delete_collection(self, project_id: str, model_version: Optional[str] = None) -> None:
        name = collection_name(project_id, model_version or settings.embedding_model_version)
        try:
            self.client.delete_collection(name)
            logger.info("[qdrant] Deleted collection '%s'", name)
        except Exception as exc:
            logger.warning("[qdrant] Could not delete '%s': %s", name, exc)

    # ── Upsert ────────────────────────────────────────────────────────────────

    def upsert_chunks(
        self,
        chunks_and_vectors: list[tuple[CodeChunk, List[float]]],
        project_id: str,
        model_version: Optional[str] = None,
        batch_size: int = 100,
    ) -> int:
        """Upsert (chunk, vector) pairs. Returns number of points upserted."""
        name = self.ensure_collection(project_id, model_version)
        total = 0

        for i in range(0, len(chunks_and_vectors), batch_size):
            batch = chunks_and_vectors[i: i + batch_size]
            points = [
                PointStruct(
                    id=chunk.chunk_id,
                    vector=vector,
                    payload=chunk.to_qdrant_payload(),
                )
                for chunk, vector in batch
            ]
            self.client.upsert(collection_name=name, points=points, wait=True)
            total += len(points)

        logger.info("[qdrant] Upserted %d points into '%s'", total, name)
        return total

    # ── Delete ────────────────────────────────────────────────────────────────

    def delete_file(self, project_id: str, file_path: str, model_version: Optional[str] = None) -> None:
        """Delete all vectors for a specific file (used during incremental update)."""
        name = collection_name(project_id, model_version or settings.embedding_model_version)
        try:
            self.client.delete(
                collection_name=name,
                points_selector=Filter(must=[
                    FieldCondition(key="file_path", match=MatchValue(value=file_path)),
                ]),
                wait=True,
            )
        except Exception as exc:
            logger.warning("[qdrant] Delete file '%s' failed: %s", file_path, exc)

    def purge_project(self, project_id: str, model_version: Optional[str] = None) -> None:
        """
        Purge all vectors for a project (GDPR right to erasure — CDC §IDX-06).
        Deletes the entire collection.
        """
        self.delete_collection(project_id, model_version)
        logger.info("[qdrant] Project '%s' fully purged", project_id)

    # ── Search ────────────────────────────────────────────────────────────────

    def dense_search(
        self,
        query_vector: List[float],
        project_id: str,
        allowed_roles: List[str],
        top_k: int = 20,
        score_threshold: float = 0.65,
        extra_filter: Optional[Filter] = None,
        model_version: Optional[str] = None,
    ) -> list:
        """
        Dense cosine similarity search with mandatory RBAC pre-filter.

        Uses query_points (qdrant-client >= 1.10). The older search() method
        was removed in recent client versions.
        """
        name = collection_name(project_id, model_version or settings.embedding_model_version)

        # RBAC pre-filter — ALWAYS applied, NEVER bypassed
        rbac_must = [
            FieldCondition(key="project_id", match=MatchValue(value=project_id)),
            FieldCondition(key="allowed_roles", match=MatchAny(any=allowed_roles)),
        ]
        rbac_filter = Filter(must=rbac_must)

        if extra_filter:
            rbac_filter = Filter(must=rbac_must + (extra_filter.must or []))

        try:
            response = self.client.query_points(
                collection_name=name,
                query=query_vector,
                query_filter=rbac_filter,
                limit=top_k,
                with_payload=True,
                score_threshold=score_threshold,
            )
            return response.points
        except Exception as exc:
            logger.error("[qdrant] Dense search error: %s", exc)
            return []

    def get_collection_info(self, project_id: str, model_version: Optional[str] = None) -> dict:
        name = collection_name(project_id, model_version or settings.embedding_model_version)
        try:
            info = self.client.get_collection(name)
            # `vectors_count` was deprecated/removed in favour of `points_count`
            # in recent qdrant-client versions — try both for compatibility.
            points_count = getattr(info, "points_count", None)
            if points_count is None:
                points_count = getattr(info, "vectors_count", None)

            return {
                "name": name,
                "vectors_count": points_count,
                "indexed_vectors_count": getattr(info, "indexed_vectors_count", None),
                "status": str(info.status),
            }
        except Exception as exc:
            return {"name": name, "error": str(exc)}

    def list_project_collections(self) -> list[str]:
        return [c.name for c in self.client.get_collections().collections]