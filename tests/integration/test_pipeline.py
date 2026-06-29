"""
Integration smoke test for the full RAG pipeline.
Requires: Qdrant running on localhost:6333, no GPU needed (fastembed local).

Run: pytest tests/integration/ -v -m integration
"""
from __future__ import annotations

import asyncio
import os
import pytest

pytestmark = pytest.mark.integration

PYTHON_SAMPLE = '''
import hashlib
from typing import Optional

def hash_password(password: str, salt: Optional[str] = None) -> str:
    """Hash a password using SHA-256 with an optional salt."""
    if salt:
        password = salt + password
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password: str, hashed: str, salt: Optional[str] = None) -> bool:
    """Verify that a plain-text password matches its hash."""
    return hash_password(password, salt) == hashed

class UserAuth:
    def __init__(self, salt: str):
        self.salt = salt

    def register(self, username: str, password: str) -> dict:
        return {
            "username": username,
            "hash": hash_password(password, self.salt),
        }

    def login(self, username: str, password: str, stored_hash: str) -> bool:
        return verify_password(password, stored_hash, self.salt)
'''


@pytest.fixture(scope="module")
def qdrant_url():
    return os.getenv("QDRANT_URL", "http://localhost:6333")


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def store(qdrant_url):
    from rag.storage.qdrant_store import QdrantStore
    return QdrantStore(url=qdrant_url, api_key="rag-local-dev-key-change-in-prod")


@pytest.fixture(scope="module")
def embedder():
    from rag.embeddings.pipeline import EmbeddingPipeline
    return EmbeddingPipeline(
        model_name="nomic-ai/nomic-embed-code",
        model_version="v1-0",
        model_url="",  # fastembed local
    )


@pytest.fixture(scope="module")
def chunker():
    from rag.chunking.ast_chunker import ASTChunker
    return ASTChunker()


@pytest.fixture(scope="module")
def scanner():
    from rag.ingestion.secret_scanner import SecretScanner
    return SecretScanner(enabled=True)


PROJECT_ID = "test-integration-project"
ALLOWED_ROLES = ["developer"]


class TestFullPipeline:

    @pytest.mark.asyncio
    async def test_chunk_embed_store_retrieve(self, chunker, scanner, embedder, store):
        from rag.chunking.deduplication import assign_chunk_ids, deduplicate_chunks

        # 1. Scan
        redacted, had_secrets = scanner.scan_and_redact(PYTHON_SAMPLE, "auth.py")
        assert had_secrets is False

        # 2. Chunk
        chunks = chunker.chunk_file(
            file_content=redacted,
            file_path="auth/utils.py",
            language="python",
            project_id=PROJECT_ID,
            tenant_id="test-tenant",
            allowed_roles=ALLOWED_ROLES,
            commit_hash="deadbeef",
            branch="main",
            repository_name="test-repo",
        )
        assert len(chunks) >= 2

        # 3. Dedup + IDs
        unique = deduplicate_chunks(chunks)
        assign_chunk_ids(unique)
        assert all(c.chunk_id for c in unique)

        # 4. Embed
        embedded = await embedder.embed_chunks(unique, show_progress=False)
        assert len(embedded) == len(unique)

        # 5. Upsert
        upserted = store.upsert_chunks(embedded, PROJECT_ID)
        assert upserted == len(unique)

        # 6. Dense search — should find hash_password
        query_vector = await embedder.embed_single("function that hashes a password with SHA256")
        results = store.dense_search(
            query_vector=query_vector,
            project_id=PROJECT_ID,
            allowed_roles=ALLOWED_ROLES,
            top_k=5,
            score_threshold=0.3,  # lower threshold for test
        )
        assert len(results) >= 1
        names = [r.payload.get("node_name", "") for r in results]
        assert any("hash" in n.lower() or "password" in n.lower() for n in names), \
            f"Expected hash/password function in results, got: {names}"

    @pytest.mark.asyncio
    async def test_rbac_isolation(self, chunker, embedder, store):
        """Users from a different project must get zero results."""
        from rag.chunking.deduplication import assign_chunk_ids, deduplicate_chunks

        query_vector = await embedder.embed_single("hash password")
        results = store.dense_search(
            query_vector=query_vector,
            project_id="completely-different-project",
            allowed_roles=ALLOWED_ROLES,
            top_k=5,
            score_threshold=0.0,
        )
        assert len(results) == 0, "RBAC leak: results returned for wrong project"

    @pytest.mark.asyncio
    async def test_secrets_not_in_index(self, chunker, scanner, embedder, store):
        """Confirm secrets are redacted before reaching Qdrant."""
        content_with_secret = PYTHON_SAMPLE + '\nAPI_KEY = "sk-' + "x" * 40 + '"'
        redacted, had_secrets = scanner.scan_and_redact(content_with_secret)
        assert had_secrets is True
        assert "sk-" + "x" * 40 not in redacted

    def test_cleanup(self, store):
        """Clean up test collection after integration tests."""
        store.purge_project(PROJECT_ID)
        info = store.get_collection_info(PROJECT_ID)
        assert "error" in info or info.get("vectors_count", 0) == 0
