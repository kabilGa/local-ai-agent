from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import settings
from ..ingestion.file_filter import get_language, should_index_file
from ..ingestion.git_connector import GitConnector
from ..ingestion.secret_scanner import SecretScanner
from ..chunking.ast_chunker import ASTChunker
from ..chunking.deduplication import assign_chunk_ids, deduplicate_chunks
from ..embeddings.pipeline import EmbeddingPipeline
from ..storage.qdrant_store import QdrantStore
from ..metrics.prometheus import (
    CHUNKS_INDEXED,
    FILES_INDEXED,
    FILES_SKIPPED,
    SECRETS_DETECTED,
    WEBHOOK_EVENTS,
)

logger = logging.getLogger(__name__)


# ── Branch policy ─────────────────────────────────────────────────────────────

def should_index_branch(branch: str) -> bool:
    """
    Only index priority branches + release/hotfix branches.
    Feature branches are excluded to avoid index bloat (CDC §8.3).
    """
    if branch in settings.priority_branches:
        return True
    return branch.startswith(("release/", "hotfix/", "fix/"))


# ── Webhook signature verification ───────────────────────────────────────────

def verify_webhook_signature(body: bytes, signature: str, secret: str) -> bool:
    """
    Verify HMAC-SHA256 webhook signature from GitLab or GitHub.
    Returns False if the signature is invalid or missing.
    """
    if not signature or not secret:
        return False

    # GitHub: "sha256=<hex>"
    if signature.startswith("sha256="):
        expected = "sha256=" + hmac.new(
            secret.encode(), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    # GitLab: plain token comparison
    return hmac.compare_digest(secret, signature)


# ── Incremental indexer ───────────────────────────────────────────────────────

class IncrementalIndexer:
    """
    Handles delta (incremental) re-indexation triggered by Git webhooks.

    On each push event:
    1. Identify changed files from the commit payload
    2. Delete their existing vectors from Qdrant
    3. Re-index only those files in their new version

    This keeps the index fresh without full re-indexation.
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
        self._queue: asyncio.Queue = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None

    # ── Worker lifecycle ──────────────────────────────────────────────────────

    async def start_worker(self) -> None:
        """Start the background queue worker. Call once on app startup."""
        self._worker_task = asyncio.create_task(self._process_queue())
        logger.info("[incremental] Worker started")

    async def stop_worker(self) -> None:
        if self._worker_task:
            self._worker_task.cancel()

    # ── Webhook ingestion ─────────────────────────────────────────────────────

    async def handle_webhook(self, payload: Dict[str, Any], event_type: str) -> str:
        """
        Parse a GitLab/GitHub webhook payload and enqueue the relevant job.
        Returns a status string for the HTTP response.
        """
        WEBHOOK_EVENTS.labels(event_type=event_type).inc()

        # Push event → incremental re-index
        if event_type in ("Push Hook", "push"):
            job = self._parse_push_event(payload, event_type)
            if job is None:
                return "skipped:no_changes"

            branch = job.get("branch", "")
            if not should_index_branch(branch):
                logger.info("[incremental] Branch '%s' excluded from indexing", branch)
                return f"skipped:branch_excluded:{branch}"

            await self._queue.put(job)
            logger.info("[incremental] Queued delta job for branch '%s' (%d files)",
                        branch, len(job.get("changed_files", [])))
            return "queued"

        # Delete event → purge project
        if event_type in ("Repository Delete Hook", "delete"):
            project_id = str(
                payload.get("project", {}).get("id", payload.get("repository", {}).get("id", ""))
            )
            if project_id:
                self.store.purge_project(project_id)
                logger.info("[incremental] Purged project '%s'", project_id)
                return "purged"

        return f"ignored:{event_type}"

    # ── Queue processing ──────────────────────────────────────────────────────

    async def _process_queue(self) -> None:
        while True:
            try:
                job = await self._queue.get()
                await self._run_delta(job)
                self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("[incremental] Worker error: %s", exc, exc_info=True)

    async def _run_delta(self, job: Dict[str, Any]) -> None:
        project_id = job["project_id"]
        branch = job["branch"]
        changed_files: List[str] = job["changed_files"]
        git_token: str = job.get("git_token", "")
        repository_url: str = job["repository_url"]
        allowed_roles: List[str] = job.get("allowed_roles", ["developer"])
        tenant_id: str = job.get("tenant_id", "")
        sensitivity_level: str = job.get("sensitivity_level", "internal")

        connector = GitConnector(
            repo_url=repository_url,
            token=git_token,
            project_id=project_id,
        )
        local_path = str(Path(settings.git_workspace) / project_id / branch)

        try:
            repo = await asyncio.to_thread(connector.clone_or_update, local_path)
        except Exception as exc:
            logger.error("[incremental] Git update failed for %s: %s", repository_url, exc)
            return

        commit_hash = connector.get_commit_hash(repo, branch)
        repo_name = repository_url.rstrip("/").split("/")[-1].replace(".git", "")

        for file_path_str in changed_files:
            file_path = Path(local_path) / file_path_str

            # Step 1 — Remove stale vectors for this file
            self.store.delete_file(project_id, file_path_str)

            # Step 2 — Check if file still exists and is indexable
            if not file_path.exists() or not should_index_file(file_path):
                FILES_SKIPPED.labels(reason="excluded_extension").inc()
                logger.debug("[incremental] Skipping deleted/excluded file %s", file_path_str)
                continue

            language = get_language(file_path)
            if not language:
                continue

            content = connector.read_file(repo, file_path_str, branch)
            if content is None:
                continue

            # Step 3 — Scan for secrets (mandatory)
            redacted, had_secrets = self.scanner.scan_and_redact(content, file_path_str)
            if had_secrets:
                SECRETS_DETECTED.inc()

            # Step 4 — Re-chunk
            try:
                chunks = self.chunker.chunk_file(
                    file_content=redacted,
                    file_path=file_path_str,
                    language=language,
                    project_id=project_id,
                    tenant_id=tenant_id,
                    allowed_roles=allowed_roles,
                    sensitivity_level=sensitivity_level,
                    commit_hash=commit_hash,
                    branch=branch,
                    repository_name=repo_name,
                    has_secrets_redacted=had_secrets,
                )
            except Exception as exc:
                logger.warning("[incremental] Chunk error %s: %s", file_path_str, exc)
                FILES_SKIPPED.labels(reason="parse_error").inc()
                continue

            unique = deduplicate_chunks(chunks)
            assign_chunk_ids(unique)

            # Step 5 — Embed + upsert
            embedded = await self.embedder.embed_chunks(unique, show_progress=False)
            self.store.upsert_chunks(embedded, project_id)

            FILES_INDEXED.labels(language=language).inc()
            for chunk in unique:
                CHUNKS_INDEXED.labels(language=language).inc()

        logger.info("[incremental] Delta update complete — %d files for project %s",
                    len(changed_files), project_id)

    # ── Payload parsers ───────────────────────────────────────────────────────

    @staticmethod
    def _parse_push_event(payload: Dict[str, Any], event_type: str) -> Optional[Dict[str, Any]]:
        """Normalise GitLab / GitHub push payloads into a common job dict."""
        changed_files: List[str] = []

        # GitLab format
        if event_type == "Push Hook":
            project = payload.get("project", {})
            for commit in payload.get("commits", []):
                changed_files.extend(commit.get("added", []))
                changed_files.extend(commit.get("modified", []))
                # Deleted files: vectors will be removed by delete_file, no re-index needed
            ref = payload.get("ref", "refs/heads/main")
            branch = ref.split("/")[-1]
            project_id = str(project.get("id", ""))
            repo_url = project.get("git_http_url", "")

        # GitHub format
        else:
            repo = payload.get("repository", {})
            for commit in payload.get("commits", []):
                changed_files.extend(commit.get("added", []))
                changed_files.extend(commit.get("modified", []))
            ref = payload.get("ref", "refs/heads/main")
            branch = ref.split("/")[-1]
            project_id = str(repo.get("id", ""))
            repo_url = repo.get("clone_url", "")

        if not changed_files or not project_id:
            return None

        # Deduplicate paths
        changed_files = list(dict.fromkeys(changed_files))

        return {
            "project_id": project_id,
            "branch": branch,
            "repository_url": repo_url,
            "changed_files": changed_files,
            "commit_hash": payload.get("after", "unknown"),
        }
