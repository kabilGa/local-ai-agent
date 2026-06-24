from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class CodeChunk:
    """
    Single indexed unit of code.
    RBAC fields (project_id, tenant_id, allowed_roles, sensitivity_level)
    MUST always be set before indexing — they are the access control boundary.
    """

    # ── Content ───────────────────────────────────────────────────────────────
    content: str                        # Code after secret redaction
    file_path: str                      # Relative path in repo
    language: str                       # python | typescript | go | …
    node_type: str                      # function | class | method | module | config
    node_name: str                      # Identifier name
    start_line: int
    end_line: int

    # ── Structural context ────────────────────────────────────────────────────
    parent_class: Optional[str] = None
    imports_context: str = ""           # File-level imports prepended to chunk
    docstring: Optional[str] = None

    # ── Version ───────────────────────────────────────────────────────────────
    commit_hash: str = "unknown"
    branch: str = "main"
    repository_name: str = ""

    # ── RBAC — NEVER OMIT ─────────────────────────────────────────────────────
    project_id: str = ""
    tenant_id: str = ""
    allowed_roles: List[str] = field(default_factory=list)
    sensitivity_level: str = "internal"   # public | internal | confidential | top_secret

    # ── Symbol graph ──────────────────────────────────────────────────────────
    calls: List[str] = field(default_factory=list)      # Functions called in this chunk
    called_by: List[str] = field(default_factory=list)  # Populated by SymbolGraph
    imports: List[str] = field(default_factory=list)    # Module names imported

    # ── Quality / provenance ──────────────────────────────────────────────────
    has_secrets_redacted: bool = False
    chunk_hash: str = ""           # SHA-256 of normalised content (deduplication)
    chunk_id: str = ""             # UUID assigned at indexing time
    embedding_model: str = ""
    embedding_model_version: str = ""
    indexed_at: str = ""
    file_last_modified: str = ""

    # ── Convenience ───────────────────────────────────────────────────────────

    def to_qdrant_payload(self) -> dict:
        """Serialise to Qdrant point payload (all fields, flat dict)."""
        return {
            "chunk_id": self.chunk_id,
            "chunk_hash": self.chunk_hash,
            "content": self.content,
            "file_path": self.file_path,
            "language": self.language,
            "node_type": self.node_type,
            "node_name": self.node_name,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "parent_class": self.parent_class or "",
            "imports_context": self.imports_context,
            "docstring": self.docstring or "",
            "commit_hash": self.commit_hash,
            "branch": self.branch,
            "repository_name": self.repository_name,
            # RBAC
            "project_id": self.project_id,
            "tenant_id": self.tenant_id,
            "allowed_roles": self.allowed_roles,
            "sensitivity_level": self.sensitivity_level,
            # Symbol graph
            "calls": self.calls,
            "called_by": self.called_by,
            "imports": self.imports,
            # Quality
            "has_secrets_redacted": self.has_secrets_redacted,
            "embedding_model": self.embedding_model,
            "embedding_model_version": self.embedding_model_version,
            "indexed_at": self.indexed_at,
            "file_last_modified": self.file_last_modified,
        }

    @property
    def fqn(self) -> str:
        """Fully qualified name: repo::file::class::function."""
        parts = [self.repository_name, self.file_path]
        if self.parent_class:
            parts.append(self.parent_class)
        parts.append(self.node_name)
        return "::".join(p for p in parts if p)
