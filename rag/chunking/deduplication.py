from __future__ import annotations

import hashlib
from typing import List

from .models import CodeChunk


def compute_chunk_hash(content: str) -> str:
    """
    SHA-256 of whitespace-normalised content.
    Detects identical code that appears on multiple branches.
    """
    normalised = " ".join(content.split())
    return hashlib.sha256(normalised.encode()).hexdigest()


def deduplicate_chunks(chunks: List[CodeChunk]) -> List[CodeChunk]:
    """
    Remove duplicate chunks by content hash.
    When the same function exists on multiple branches, keep the first seen.
    The chunk_hash field is set/updated in place.
    """
    seen: dict[str, CodeChunk] = {}
    for chunk in chunks:
        h = chunk.chunk_hash or compute_chunk_hash(chunk.content)
        chunk.chunk_hash = h
        if h not in seen:
            seen[h] = chunk
    return list(seen.values())


def assign_chunk_ids(chunks: List[CodeChunk]) -> List[CodeChunk]:
    """
    Assign stable UUIDs derived from chunk_hash + project_id.
    Deterministic: same chunk always gets the same ID (idempotent upsert).
    """
    import uuid
    for chunk in chunks:
        seed = f"{chunk.project_id}::{chunk.chunk_hash}"
        chunk.chunk_id = str(uuid.uuid5(uuid.NAMESPACE_OID, seed))
    return chunks
