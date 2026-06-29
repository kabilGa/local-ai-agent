from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ── Retrieve ──────────────────────────────────────────────────────────────────

class RetrieveRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=2000, description="Developer query")
    user_id: str = Field(..., min_length=1)
    project_ids: List[str] = Field(..., min_length=1, description="Authorised project IDs")
    allowed_roles: List[str] = Field(..., min_length=1, description="User roles for RBAC")
    top_k: int = Field(5, ge=1, le=20)
    filters: Optional[Dict[str, Any]] = Field(
        None,
        description="Optional: language, node_types, file_path_prefix, branch",
    )
    options: Optional[Dict[str, bool]] = Field(
        None,
        description="Optional: use_reranker, include_symbol_graph, use_hyde",
    )

    @field_validator("project_ids")
    @classmethod
    def no_empty_project_ids(cls, v: List[str]) -> List[str]:
        if any(not p.strip() for p in v):
            raise ValueError("project_ids must not contain empty strings")
        return v


class SourceReference(BaseModel):
    file_path: str
    start_line: int
    end_line: int
    commit_hash: str
    repository_name: str
    node_name: str
    language: str
    relevance_score: float


class RetrieveResponse(BaseModel):
    query: str
    assembled_context: str          # Ready to inject into the LLM prompt
    sources: List[SourceReference]  # Exact references for anti-hallucination
    retrieval_time_ms: int
    cache_hit: bool
    chunks_found: int
    injection_detected: bool = False


# ── Index ─────────────────────────────────────────────────────────────────────

class IndexRequest(BaseModel):
    project_id: str = Field(..., min_length=1)
    repository_url: str = Field(..., min_length=5)
    git_token: str = Field(..., min_length=1, description="Read-only Git token")
    branch: str = Field("main", min_length=1)
    tenant_id: str = Field("", description="Tenant identifier for multi-tenant isolation")
    allowed_roles: List[str] = Field(
        default_factory=lambda: ["developer"],
        description="Roles allowed to query this project's chunks",
    )
    sensitivity_level: str = Field(
        "internal",
        pattern="^(public|internal|confidential|top_secret)$",
    )


class IndexResponse(BaseModel):
    job_id: str
    project_id: str
    status: str
    message: str


class IndexStatusResponse(BaseModel):
    job_id: str
    project_id: str
    status: str                     # pending | running | success | error
    started_at: Optional[str]
    finished_at: Optional[str]
    files_total: int
    files_indexed: int
    files_skipped: int
    chunks_created: int
    secrets_found: int
    error: Optional[str]
    progress_pct: float


class PurgeResponse(BaseModel):
    project_id: str
    status: str
    message: str


# ── Webhooks ──────────────────────────────────────────────────────────────────

class WebhookResponse(BaseModel):
    status: str
    detail: str


# ── Health ────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str          # ok | degraded | error
    version: str
    components: Dict[str, str]


class ReadinessResponse(BaseModel):
    ready: bool
    checks: Dict[str, bool]
