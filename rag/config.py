from __future__ import annotations

from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Qdrant ────────────────────────────────────────────────────────────────
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = "change-me"

    # ── Embeddings ────────────────────────────────────────────────────────────
    # If empty → fastembed local; if set → remote TEI HTTP server
    embedding_model_url: str = ""
    embedding_model_name: str = "nomic-ai/nomic-embed-code"
    embedding_model_version: str = "v1-0"
    embedding_dim: int = 768
    embedding_batch_size: int = 32
    embedding_max_concurrent: int = 4

    # ── Reranker ──────────────────────────────────────────────────────────────
    reranker_url: str = "http://localhost:8081"
    reranker_enabled: bool = False

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379"

    # ── Git ───────────────────────────────────────────────────────────────────
    git_workspace: str = "/tmp/rag-repos"
    webhook_secret: str = "change-me-webhook-secret"
    priority_branches: List[str] = ["main", "master", "develop", "staging"]

    # ── Security ──────────────────────────────────────────────────────────────
    secret_scanner_enabled: bool = True
    gitleaks_binary: str = "gitleaks"

    # ── Retrieval ─────────────────────────────────────────────────────────────
    default_top_k: int = 5
    reranker_top_k: int = 20
    score_threshold: float = 0.65
    rrf_k: int = 60

    # ── Cache ─────────────────────────────────────────────────────────────────
    cache_enabled: bool = True
    cache_ttl_seconds: int = 3600
    cache_similarity_threshold: float = 0.95

    # ── Context assembly ──────────────────────────────────────────────────────
    max_context_tokens: int = 8000

    # ── API ───────────────────────────────────────────────────────────────────
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "info"

    @field_validator("embedding_model_version")
    @classmethod
    def sanitize_version(cls, v: str) -> str:
        # Used as part of Qdrant collection names — no dots or slashes
        return v.replace(".", "-").replace("/", "-")


settings = Settings()
