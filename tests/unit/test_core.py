"""
Unit tests for deduplication, SymbolGraph, and QueryPreprocessor.
"""
from __future__ import annotations

import pytest

from rag.chunking.deduplication import (
    assign_chunk_ids,
    compute_chunk_hash,
    deduplicate_chunks,
)
from rag.chunking.models import CodeChunk
from rag.chunking.symbol_graph import SymbolGraph
from rag.retrieval.query_preprocessor import QueryPreprocessor


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_chunk(content: str, node_name: str = "func", project_id: str = "p1") -> CodeChunk:
    from rag.chunking.ast_chunker import _normalize_hash
    return CodeChunk(
        content=content,
        file_path="test.py",
        language="python",
        node_type="function",
        node_name=node_name,
        start_line=1,
        end_line=5,
        project_id=project_id,
        tenant_id="t1",
        allowed_roles=["developer"],
        chunk_hash=_normalize_hash(content),
    )


# ── Deduplication ─────────────────────────────────────────────────────────────

class TestDeduplication:

    def test_removes_duplicate_content(self):
        c1 = make_chunk("def foo(): return 1", "foo")
        c2 = make_chunk("def foo(): return 1", "foo")   # exact duplicate
        result = deduplicate_chunks([c1, c2])
        assert len(result) == 1

    def test_keeps_distinct_chunks(self):
        c1 = make_chunk("def foo(): return 1", "foo")
        c2 = make_chunk("def bar(): return 2", "bar")
        result = deduplicate_chunks([c1, c2])
        assert len(result) == 2

    def test_whitespace_normalisation(self):
        c1 = make_chunk("def foo():  return  1", "foo")
        c2 = make_chunk("def foo(): return 1", "foo")   # same after normalisation
        result = deduplicate_chunks([c1, c2])
        assert len(result) == 1

    def test_hash_deterministic(self):
        h1 = compute_chunk_hash("def foo(): pass")
        h2 = compute_chunk_hash("def foo(): pass")
        assert h1 == h2

    def test_hash_differs_for_different_content(self):
        h1 = compute_chunk_hash("def foo(): pass")
        h2 = compute_chunk_hash("def bar(): pass")
        assert h1 != h2

    def test_chunk_hash_set_by_dedup(self):
        c = make_chunk("def foo(): pass")
        c.chunk_hash = ""   # clear
        result = deduplicate_chunks([c])
        assert len(result[0].chunk_hash) == 64


class TestAssignChunkIds:

    def test_ids_are_uuids(self):
        import re
        c = make_chunk("def foo(): pass")
        c.chunk_hash = compute_chunk_hash(c.content)
        assign_chunk_ids([c])
        uuid_re = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
        assert re.match(uuid_re, c.chunk_id)

    def test_ids_are_deterministic(self):
        c1 = make_chunk("def foo(): pass")
        c2 = make_chunk("def foo(): pass")
        c1.chunk_hash = c2.chunk_hash = compute_chunk_hash("def foo(): pass")
        assign_chunk_ids([c1])
        assign_chunk_ids([c2])
        assert c1.chunk_id == c2.chunk_id

    def test_different_projects_different_ids(self):
        c1 = make_chunk("def foo(): pass", project_id="p1")
        c2 = make_chunk("def foo(): pass", project_id="p2")
        c1.chunk_hash = c2.chunk_hash = compute_chunk_hash("def foo(): pass")
        assign_chunk_ids([c1, c2])
        assert c1.chunk_id != c2.chunk_id


# ── SymbolGraph ───────────────────────────────────────────────────────────────

class TestSymbolGraph:

    def test_add_and_query_call_edge(self):
        g = SymbolGraph()
        g.add_call_edge("repo::auth.py::login", "repo::db.py::query_user")
        callees = g.get_callees("repo::auth.py::login")
        assert "repo::db.py::query_user" in callees

    def test_get_callers(self):
        g = SymbolGraph()
        g.add_call_edge("repo::api.py::handle_request", "repo::auth.py::login")
        g.add_call_edge("repo::cli.py::run", "repo::auth.py::login")
        callers = g.get_callers("repo::auth.py::login")
        assert "repo::api.py::handle_request" in callers
        assert "repo::cli.py::run" in callers

    def test_search_by_name(self):
        g = SymbolGraph()
        g.add_call_edge("repo::auth.py::authenticate_user", "repo::db.py::find_user")
        results = g.search_by_name("authenticate_user")
        assert any("authenticate_user" in r for r in results)

    def test_empty_graph_returns_empty(self):
        g = SymbolGraph()
        assert g.get_callers("nothing::here") == []
        assert g.get_callees("nothing::here") == []

    def test_graph_len(self):
        g = SymbolGraph()
        g.add_call_edge("a::foo", "b::bar")
        assert len(g) >= 2

    def test_serialize_roundtrip(self):
        g = SymbolGraph()
        g.add_call_edge("a::foo", "b::bar")
        data = g.to_dict()
        g2 = SymbolGraph.from_dict(data)
        assert g2.get_callees("a::foo") == ["b::bar"]


# ── QueryPreprocessor ─────────────────────────────────────────────────────────

class TestQueryPreprocessor:

    @pytest.fixture
    def pp(self):
        return QueryPreprocessor()

    def test_normalises_whitespace(self, pp):
        result = pp.preprocess("  how   does  this   work  ")
        assert "  " not in result["normalised"]

    def test_detects_python(self, pp):
        result = pp.preprocess("def authenticate_user(self, token): pass")
        assert result["detected_language"] == "python"

    def test_detects_typescript(self, pp):
        result = pp.preprocess("interface UserService { getUser(id: string): Promise<User> }")
        assert result["detected_language"] == "typescript"

    def test_classifies_debugging(self, pp):
        result = pp.preprocess("I'm getting a TypeError exception in my code")
        assert result["query_type"] == "debugging"

    def test_classifies_security(self, pp):
        result = pp.preprocess("Is there a SQL injection vulnerability here?")
        assert result["query_type"] == "security"

    def test_classifies_refactoring(self, pp):
        result = pp.preprocess("How can I refactor this to improve performance?")
        assert result["query_type"] == "refactoring"

    def test_extracts_identifiers(self, pp):
        result = pp.preprocess("Where is authenticate_user called in the codebase?")
        assert "authenticate_user" in result["keywords"]

    def test_unknown_language_returns_none(self, pp):
        result = pp.preprocess("How do I bake a cake?")
        assert result["detected_language"] is None

    def test_general_classification_fallback(self, pp):
        result = pp.preprocess("List all available configuration options")
        assert result["query_type"] == "general"

    def test_output_structure(self, pp):
        result = pp.preprocess("def foo(): pass")
        assert "original" in result
        assert "normalised" in result
        assert "detected_language" in result
        assert "keywords" in result
        assert "query_type" in result
        assert "hypothetical_snippet" in result
