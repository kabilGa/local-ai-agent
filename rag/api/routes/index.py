from __future__ import annotations

import hashlib
import hmac
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Body

from ...api.schemas import (
    IndexRequest,
    IndexResponse,
    IndexStatusResponse,
    PurgeResponse,
    WebhookResponse,
)
from ...config import settings
from ...indexing.incremental import IncrementalIndexer, verify_webhook_signature
from ...indexing.indexer import Indexer, get_job, list_jobs
from ...storage.qdrant_store import QdrantStore

logger = logging.getLogger(__name__)

router = APIRouter()


def get_indexer(request: Request) -> Indexer:
    return request.app.state.indexer


def get_incremental(request: Request) -> IncrementalIndexer:
    return request.app.state.incremental_indexer


def get_store(request: Request) -> QdrantStore:
    return request.app.state.store


# ── Trigger full indexation ───────────────────────────────────────────────────

@router.post(
    "",
    response_model=IndexResponse,
    summary="Trigger full repository indexation",
    status_code=202,
)
async def trigger_index(
    body: IndexRequest,
    indexer: Indexer = Depends(get_indexer),
) -> IndexResponse:
    """
    Submit a full indexation job for a Git repository.
    Returns immediately with a job_id; poll /v1/index/status/{job_id} for progress.
    """
    job = indexer.submit_job(
        project_id=body.project_id,
        repository_url=body.repository_url,
        git_token=body.git_token,
        branch=body.branch,
        allowed_roles=body.allowed_roles,
        tenant_id=body.tenant_id,
        sensitivity_level=body.sensitivity_level,
    )
    logger.info("[index] Job %s submitted for project '%s'", job.job_id, body.project_id)
    return IndexResponse(
        job_id=job.job_id,
        project_id=body.project_id,
        status="pending",
        message=f"Indexation job {job.job_id} queued. Branch: {body.branch}",
    )


# ── Job status ────────────────────────────────────────────────────────────────

@router.get(
    "/status/{job_id}",
    response_model=IndexStatusResponse,
    summary="Poll indexation job status",
)
async def get_index_status(job_id: str) -> IndexStatusResponse:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return IndexStatusResponse(**job.to_dict())


@router.get(
    "/jobs",
    response_model=list[IndexStatusResponse],
    summary="List all indexation jobs (optionally filter by project)",
)
async def list_index_jobs(project_id: str | None = None) -> list[IndexStatusResponse]:
    jobs = list_jobs(project_id=project_id)
    return [IndexStatusResponse(**j.to_dict()) for j in jobs]


# ── Purge (GDPR right to erasure — CDC §IDX-06) ───────────────────────────────

@router.delete(
    "/{project_id}",
    response_model=PurgeResponse,
    summary="Purge all indexed data for a project (Admin only)",
)
async def purge_project(
    project_id: str,
    store: QdrantStore = Depends(get_store),
) -> PurgeResponse:
    """
    Permanently deletes all vectors, metadata, and cache entries for a project.
    This operation is irreversible. Requires admin role (enforced at gateway level).
    CDC §IDX-06: purge must be complete and verifiable.
    """
    store.purge_project(project_id)
    logger.warning("[purge] Project '%s' fully purged from Qdrant", project_id)
    return PurgeResponse(
        project_id=project_id,
        status="purged",
        message=f"All indexed data for project '{project_id}' has been permanently deleted.",
    )


# ── Collection info ───────────────────────────────────────────────────────────

@router.get(
    "/{project_id}/info",
    summary="Get collection stats for a project",
)
async def project_info(
    project_id: str,
    store: QdrantStore = Depends(get_store),
) -> dict:
    return store.get_collection_info(project_id)


# ── Git webhook ───────────────────────────────────────────────────────────────

@router.post(
    "/webhook",
    response_model=WebhookResponse,
    summary="Receive Git push webhooks for incremental re-indexation",
)
async def git_webhook(
    request: Request,
    x_gitlab_token: str | None = Header(None),
    x_hub_signature_256: str | None = Header(None),
    x_gitlab_event: str | None = Header(None),
    x_github_event: str | None = Header(None),
    incremental: IncrementalIndexer = Depends(get_incremental),
) -> WebhookResponse:
    """
    Endpoint for GitLab / GitHub push webhooks.
    Signature is verified before any processing (CDC §8.1 webhook security).
    """
    body_bytes = await request.body()

    # Verify signature
    signature = x_gitlab_token or x_hub_signature_256 or ""
    if not verify_webhook_signature(body_bytes, signature, settings.webhook_secret):
        logger.warning("[webhook] Invalid signature from %s", request.client.host if request.client else "?")
        raise HTTPException(status_code=403, detail="Invalid webhook signature")

    payload = await request.json()
    event_type = x_gitlab_event or x_github_event or "unknown"

    result = await incremental.handle_webhook(payload, event_type)
    logger.info("[webhook] Event '%s' → %s", event_type, result)

    return WebhookResponse(status="received", detail=result)
