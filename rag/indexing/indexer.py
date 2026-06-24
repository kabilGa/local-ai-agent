from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..chunking.ast_chunker import ASTChunker
from ..chunking.deduplication import assign_chunk_ids, deduplicate_chunks
from ..chunking.symbol_graph import SymbolGraph
from ..config import settings
from ..embeddings.pipeline import EmbeddingPipeline
from ..ingestion.file_filter import get_language, should_index_file
from ..ingestion.git_connector import GitConnector
from ..ingestion.secret_scanner import SecretScanner
from ..metrics.prometheus import (
    ACTIVE_INDEX_JOBS,
    CHUNKS_INDEXED,
    FILES_INDEXED,
    FILES_SKIPPED,
    INDEXING_DURATION,
    INDEXING_JOBS,
    SECRETS_DETECTED,
)
from ..storage.qdrant_store import QdrantStore

logger = logging.getLogger(__name__)


# ── Job status ────────────────────────────────────────────────────────────────

@dataclass
class IndexJob:
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str = ""
    repository_url: str = ""
    branch: str = "main"
    status: str = "pending"          # pending | running | success | error
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    files_total: int = 0
    files_indexed: int = 0
    files_skipped: int = 0
    chunks_created: int = 0
    secrets_found: int = 0
    error: Optional[str] = None
    progress_pct: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "project_id": self.project_id,
            "repository_url": self.repository_url,
            "branch": self.branch,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "files_total": self.files_total,
            "files_indexed": self.files_indexed,
            "files_skipped": self.files_skipped,
            "chunks_created": self.chunks_created,
            "secrets_found": self.secrets_found,
            "error": self.error,
            "progress_pct": round(self.progress_pct, 1),
        }


# ── Job registry (in-memory, replace with Redis for multi-node) ───────────────

_JOB_REGISTRY: Dict[str, IndexJob] = {}


def get_job(job_id: str) -> Optional[IndexJob]:
    return _JOB_REGISTRY.get(job_id)


def list_jobs(project_id: Optional[str] = None) -> List[IndexJob]:
    jobs = list(_JOB_REGISTRY.values())
    if project_id:
        jobs = [j for j in jobs if j.project_id == project_id]
    return sorted(jobs, key=lambda j: j.started_at or "", reverse=True)


# ── Indexer ───────────────────────────────────────────────────────────────────

class Indexer:
    """
    Orchestrates the full indexing pipeline for one repository:

    GitConnector → FileFilter → SecretScanner → ASTChunker
        → Deduplication → EmbeddingPipeline → QdrantStore + SymbolGraph

    Produces an IndexJob with live progress tracking.
    """

    def __init__(
        self,
        store: QdrantStore,
        embedder: EmbeddingPipeline,
        scanner: Optional[SecretScanner] = None,
        chunker: Optional[ASTChunker] = None,
    ):
        self.store = store
        self.embedder = embedder
        self.scanner = scanner or SecretScanner(
            gitleaks_binary=settings.gitleaks_binary,
            enabled=settings.secret_scanner_enabled,
        )
        self.chunker = chunker or ASTChunker()

    # ── Entry point ───────────────────────────────────────────────────────────

    def submit_job(
        self,
        project_id: str,
        repository_url: str,
        git_token: str,
        branch: str = "main",
        allowed_roles: Optional[List[str]] = None,
        tenant_id: str = "",
        sensitivity_level: str = "internal",
    ) -> IndexJob:
        """Create a job and schedule it as a background asyncio task."""
        job = IndexJob(
            project_id=project_id,
            repository_url=repository_url,
            branch=branch,
        )
        _JOB_REGISTRY[job.job_id] = job

        asyncio.create_task(
            self._run_job(
                job=job,
                git_token=git_token,
                allowed_roles=allowed_roles or ["developer"],
                tenant_id=tenant_id,
                sensitivity_level=sensitivity_level,
            )
        )
        return job

    # ── Pipeline ──────────────────────────────────────────────────────────────

    async def _run_job(
        self,
        job: IndexJob,
        git_token: str,
        allowed_roles: List[str],
        tenant_id: str,
        sensitivity_level: str,
    ) -> None:
        job.status = "running"
        job.started_at = datetime.now(timezone.utc).isoformat()
        ACTIVE_INDEX_JOBS.inc()
        t0 = time.monotonic()

        try:
            await self._execute(job, git_token, allowed_roles, tenant_id, sensitivity_level)
            job.status = "success"
            INDEXING_JOBS.labels(status="success").inc()
        except Exception as exc:
            job.status = "error"
            job.error = str(exc)
            INDEXING_JOBS.labels(status="error").inc()
            logger.error("[indexer] Job %s failed: %s", job.job_id, exc, exc_info=True)
        finally:
            job.finished_at = datetime.now(timezone.utc).isoformat()
            job.progress_pct = 100.0
            ACTIVE_INDEX_JOBS.dec()
            INDEXING_DURATION.observe(time.monotonic() - t0)

    async def _execute(
        self,
        job: IndexJob,
        git_token: str,
        allowed_roles: List[str],
        tenant_id: str,
        sensitivity_level: str,
    ) -> None:
        # Step 1 — Clone / fetch
        connector = GitConnector(
            repo_url=job.repository_url,
            token=git_token,
            project_id=job.project_id,
        )
        local_path = str(Path(settings.git_workspace) / job.project_id / job.branch)
        repo = await asyncio.to_thread(connector.clone_or_update, local_path)
        commit_hash = connector.get_commit_hash(repo, job.branch)
        repo_name = job.repository_url.rstrip("/").split("/")[-1].replace(".git", "")

        # Step 2 — Enumerate indexable files
        all_files = list(connector.list_files(repo, job.branch))
        indexable = [f for f in all_files if should_index_file(Path(local_path) / f)]
        job.files_total = len(indexable)
        logger.info("[indexer] %d / %d files to index for '%s'", len(indexable), len(all_files), repo_name)

        symbol_graph = SymbolGraph()
        all_chunks = []

        # Step 3 — Process each file
        for i, rel_path in enumerate(indexable):
            job.progress_pct = (i / max(len(indexable), 1)) * 90

            file_path_str = rel_path.as_posix()
            language = get_language(Path(local_path) / rel_path) or get_language(rel_path)
            if not language:
                FILES_SKIPPED.labels(reason="excluded_extension").inc()
                job.files_skipped += 1
                continue

            content = connector.read_file(repo, file_path_str, job.branch)
            if content is None:
                FILES_SKIPPED.labels(reason="read_error").inc()
                job.files_skipped += 1
                continue

            # MANDATORY: secret scan before any further processing
            redacted, had_secrets = self.scanner.scan_and_redact(content, file_path_str)
            if had_secrets:
                job.secrets_found += 1
                SECRETS_DETECTED.inc()

            # AST chunking
            try:
                chunks = self.chunker.chunk_file(
                    file_content=redacted,
                    file_path=file_path_str,
                    language=language,
                    project_id=job.project_id,
                    tenant_id=tenant_id,
                    allowed_roles=allowed_roles,
                    sensitivity_level=sensitivity_level,
                    commit_hash=commit_hash,
                    branch=job.branch,
                    repository_name=repo_name,
                    has_secrets_redacted=had_secrets,
                )
            except Exception as exc:
                logger.warning("[indexer] Chunk error %s: %s", file_path_str, exc)
                FILES_SKIPPED.labels(reason="parse_error").inc()
                job.files_skipped += 1
                continue

            # Build symbol graph edges
            for chunk in chunks:
                for callee in chunk.calls:
                    symbol_graph.add_call_edge(chunk.fqn, callee)

            all_chunks.extend(chunks)
            FILES_INDEXED.labels(language=language).inc()
            job.files_indexed += 1
            await asyncio.sleep(0)  # yield event loop

        # Step 4 — Deduplication + stable IDs
        unique_chunks = deduplicate_chunks(all_chunks)
        assign_chunk_ids(unique_chunks)
        logger.info("[indexer] %d unique chunks after dedup (was %d)", len(unique_chunks), len(all_chunks))

        # Step 5 — Embed
        embedded = await self.embedder.embed_chunks(unique_chunks, show_progress=True)

        # Step 6 — Upsert into Qdrant
        upserted = self.store.upsert_chunks(embedded, job.project_id)
        job.chunks_created = upserted

        # Step 7 — Persist symbol graph to Redis (best-effort)
        try:
            import redis as _redis
            r = _redis.from_url(settings.redis_url)
            symbol_graph.persist_to_redis(r, job.project_id)
        except Exception as exc:
            logger.warning("[indexer] Symbol graph persist failed: %s", exc)

        # Metrics
        for chunk in unique_chunks:
            CHUNKS_INDEXED.labels(language=chunk.language).inc()

        logger.info(
            "[indexer] Job %s done — %d files, %d chunks, %d secrets found",
            job.job_id, job.files_indexed, upserted, job.secrets_found,
        )
