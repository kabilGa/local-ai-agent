from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# ── Language hints ────────────────────────────────────────────────────────────

_LANG_HINTS: dict[str, list[str]] = {
    "python":     ["def ", "import ", "__init__", "self.", "elif ", "None", "True", "False"],
    "typescript": ["interface ", ": string", ": number", ": boolean", "async ", "=>", "const ", "export "],
    "javascript": ["function ", "const ", "let ", "var ", "require(", "module.exports"],
    "java":       ["public class", "void ", "extends ", "implements ", "System.out", "@Override"],
    "go":         ["func ", "package ", ":=", "fmt.Print", "goroutine", "chan "],
    "rust":       ["fn ", "let mut", "impl ", "use std::", "Option<", "Result<"],
    "sql":        ["SELECT ", "INSERT ", "UPDATE ", "DELETE ", "FROM ", "WHERE ", "JOIN "],
}

# ── Query type classification ─────────────────────────────────────────────────

_TYPE_KEYWORDS: dict[str, list[str]] = {
    "debugging":   ["error", "exception", "traceback", "bug", "stacktrace", "crash", "fail", "panic"],
    "security":    ["vulnerability", "cve", "injection", "xss", "sqli", "overflow", "auth", "permission", "secret"],
    "refactoring": ["refactor", "optimize", "performance", "clean", "extract", "rename", "simplify", "duplicate"],
    "testing":     ["test", "mock", "stub", "assert", "unit test", "coverage", "fixture"],
    "docs":        ["document", "explain", "what does", "how does", "readme", "comment"],
}


class QueryPreprocessor:
    """
    Prepare a raw user query for hybrid retrieval:
      - Normalisation
      - Programming language detection
      - Identifier extraction (camelCase, snake_case, PascalCase)
      - Query type classification
      - HyDE (Hypothetical Document Embeddings) — optional, requires model gateway
    """

    def preprocess(self, raw_query: str) -> dict:
        normalised = self._normalise(raw_query)
        lang = self._detect_language(raw_query)
        keywords = self._extract_identifiers(normalised)
        query_type = self._classify(normalised)

        return {
            "original": raw_query,
            "normalised": normalised,
            "detected_language": lang,
            "keywords": keywords,
            "query_type": query_type,
            "hypothetical_snippet": None,  # Populated by HyDE if enabled
        }

    # ── Normalisation ─────────────────────────────────────────────────────────

    @staticmethod
    def _normalise(q: str) -> str:
        q = re.sub(r"\s+", " ", q.strip())
        # Remove common filler phrases that don't help retrieval
        q = re.sub(r"(?i)^(can you|please|could you|how (do i|can i|to))\s+", "", q)
        return q

    # ── Language detection ────────────────────────────────────────────────────

    @staticmethod
    def _detect_language(q: str) -> Optional[str]:
        scores: dict[str, int] = {}
        for lang, hints in _LANG_HINTS.items():
            score = sum(1 for h in hints if h in q)
            if score:
                scores[lang] = score
        if not scores:
            return None
        return max(scores, key=scores.__getitem__)

    # ── Identifier extraction ─────────────────────────────────────────────────

    @staticmethod
    def _extract_identifiers(q: str) -> list[str]:
        """
        Extract camelCase, snake_case, PascalCase tokens — likely function/class names.
        These feed directly into BM25 and symbol graph search.
        """
        raw = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b", q)
        # Exclude very common English words
        stop = {"the", "and", "for", "that", "this", "with", "from", "have", "not",
                "are", "was", "can", "does", "how", "what", "when", "where", "why",
                "which", "then", "also", "into", "its", "but", "use", "get", "set"}
        return list(dict.fromkeys(t for t in raw if t.lower() not in stop))

    # ── Query classification ──────────────────────────────────────────────────

    @staticmethod
    def _classify(q: str) -> str:
        q_lower = q.lower()
        scores: dict[str, int] = {}
        for qtype, kws in _TYPE_KEYWORDS.items():
            score = sum(1 for kw in kws if kw in q_lower)
            if score:
                scores[qtype] = score
        return max(scores, key=scores.__getitem__) if scores else "general"

    # ── HyDE ──────────────────────────────────────────────────────────────────

    @staticmethod
    def generate_hyde(query: str, model_gateway) -> Optional[str]:
        """
        Hypothetical Document Embeddings:
        Ask the LLM to generate a hypothetical code snippet that would answer
        the query, then embed THAT instead of the raw query text.
        Significantly improves recall on abstract questions.

        Disabled by default (adds ~1-2s latency). Pass model_gateway=None to skip.
        """
        if model_gateway is None:
            return None
        try:
            snippet = model_gateway.generate(
                f"Write a concise code snippet (≤20 lines) that would answer "
                f"this developer question. Return ONLY code, no explanation:\n\n{query}"
            )
            return snippet.strip() if snippet else None
        except Exception as exc:
            logger.debug("[hyde] Generation failed: %s", exc)
            return None
