from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from ..chunking.symbol_graph import SymbolGraph
from ..config import settings

logger = logging.getLogger(__name__)

# ── Prompt injection patterns ─────────────────────────────────────────────────

_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?i)ignore\s+(previous|above|all)\s+instructions"),
    re.compile(r"(?i)system\s*:\s*you\s+are"),
    re.compile(r"(?i)new\s+instructions?\s*:"),
    re.compile(r"(?i)\[INST\]|\[/INST\]"),
    re.compile(r"<\|im_start\|>|<\|im_end\|>"),
    re.compile(r"(?i)disregard\s+(your|all|the)\s+(previous|prior|system)"),
    re.compile(r"(?i)you\s+are\s+now\s+(a|an|acting)"),
    re.compile(r"(?i)jailbreak|DAN mode|developer mode"),
    re.compile(r"(?i)print\s+(your|the)\s+(system\s+)?prompt"),
]

_APPROX_CHARS_PER_TOKEN = 4


class ContextAssembler:
    """
    Assemble ranked retrieval results into a structured context block
    ready to be injected into the LLM system prompt.

    Responsibilities:
    - Token budget management
    - Anti-prompt injection sanitisation (CDC §QAI-06)
    - Symbol graph enrichment (callers of retrieved functions)
    - Source reference list for anti-hallucination (CDC §F-07)
    """

    def __init__(
        self,
        max_context_tokens: int = settings.max_context_tokens,
        symbol_graph: Optional[SymbolGraph] = None,
    ):
        self.max_context_tokens = max_context_tokens
        self.symbol_graph = symbol_graph

    def assemble(
        self,
        query: str,
        ranked_results: List[Dict[str, Any]],
        include_callers: bool = True,
    ) -> Dict[str, Any]:
        """
        Build the context dict consumed by the orchestrator.

        Returns:
        {
            "query": str,
            "assembled_context": str,   # Ready to inject into prompt
            "sources": List[dict],      # Exact file/line references
            "token_count": int,
            "injection_detected": bool,
        }
        """
        primary = ranked_results[:5]
        injection_detected = False
        context_chunks: List[str] = []
        sources: List[Dict[str, Any]] = []
        token_budget = self.max_context_tokens

        # Primary chunks
        for item in primary:
            payload = self._extract_payload(item)
            if not payload:
                continue

            content, was_neutralised = self._sanitize(payload.get("content", ""), payload)
            if was_neutralised:
                injection_detected = True

            tokens = _estimate_tokens(content)
            if tokens > token_budget:
                logger.warning("[context] Token budget exhausted — stopping at %d chunks", len(context_chunks))
                break

            context_chunks.append(self._format_chunk(payload, content))
            token_budget -= tokens
            sources.append(self._make_source_ref(payload, item))

        # Symbol graph enrichment — add immediate callers
        if include_callers and self.symbol_graph and token_budget > 200:
            for item in primary:
                payload = self._extract_payload(item)
                if not payload:
                    continue
                node_name = payload.get("node_name", "")
                if not node_name:
                    continue
                callers = self.symbol_graph.get_callers(
                    f"{payload.get('repository_name', '')}::{payload.get('file_path', '')}::{node_name}",
                    depth=1,
                )
                for caller_fqn in callers[:2]:
                    caller_note = f"# Caller: {caller_fqn}\n"
                    tokens = _estimate_tokens(caller_note)
                    if tokens <= token_budget:
                        context_chunks.append(caller_note)
                        token_budget -= tokens

        assembled = "\n\n---\n\n".join(context_chunks)

        return {
            "query": query,
            "assembled_context": assembled,
            "sources": sources,
            "token_count": self.max_context_tokens - token_budget,
            "injection_detected": injection_detected,
            "chunks_used": len(context_chunks),
        }

    # ── Sanitisation ──────────────────────────────────────────────────────────

    @staticmethod
    def _sanitize(content: str, payload: Dict) -> tuple[str, bool]:
        """
        Neutralise prompt injection attempts found in retrieved code.
        CDC §QAI-06: code from the repo MUST NOT modify system instructions.
        """
        for pattern in _INJECTION_PATTERNS:
            if pattern.search(content):
                file_path = payload.get("file_path", "unknown")
                logger.warning(
                    "[context] Prompt injection neutralised in '%s' (pattern: %s)",
                    file_path, pattern.pattern,
                )
                return (
                    f"[CONTENT NEUTRALISED — INJECTION PATTERN DETECTED]\n"
                    f"# Source: {file_path} L{payload.get('start_line')}-{payload.get('end_line')}",
                    True,
                )
        return content, False

    # ── Formatting ────────────────────────────────────────────────────────────

    @staticmethod
    def _format_chunk(payload: Dict, content: str) -> str:
        file_path = payload.get("file_path", "")
        start = payload.get("start_line", "?")
        end = payload.get("end_line", "?")
        repo = payload.get("repository_name", "")
        commit = (payload.get("commit_hash") or "")[:8]
        lang = payload.get("language", "")

        header = f"# {repo}/{file_path}  L{start}-{end}  commit:{commit}"
        return f"{header}\n```{lang}\n{content}\n```"

    @staticmethod
    def _make_source_ref(payload: Dict, item: Dict) -> Dict[str, Any]:
        return {
            "file_path": payload.get("file_path", ""),
            "start_line": payload.get("start_line", 0),
            "end_line": payload.get("end_line", 0),
            "commit_hash": (payload.get("commit_hash") or "")[:8],
            "repository_name": payload.get("repository_name", ""),
            "node_name": payload.get("node_name", ""),
            "language": payload.get("language", ""),
            "relevance_score": float(item.get("rrf_score", item.get("score", 0.0))),
        }

    @staticmethod
    def _extract_payload(item: Dict) -> Optional[Dict]:
        """Handle both RRF-fused dicts and plain Qdrant ScoredPoint wrappers."""
        if "payload" in item:
            return item["payload"]
        result = item.get("result")
        if isinstance(result, dict):
            return result.get("payload")
        if result is not None and hasattr(result, "payload"):
            return result.payload
        return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _APPROX_CHARS_PER_TOKEN)
