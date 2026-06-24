"""
Unit tests for ASTChunker.
Verifies AST-based chunking correctness, fallback behaviour, and RBAC field propagation.
"""
from __future__ import annotations

import pytest

from rag.chunking.ast_chunker import ASTChunker
from rag.chunking.models import CodeChunk

COMMON_KWARGS = dict(
    project_id="proj-test",
    tenant_id="tenant-1",
    allowed_roles=["developer"],
    commit_hash="abc123",
    branch="main",
    repository_name="test-repo",
)


@pytest.fixture
def chunker():
    return ASTChunker()


# ── Python ────────────────────────────────────────────────────────────────────

class TestPythonChunking:
    SIMPLE_MODULE = '''
import os
from typing import List

def greet(name: str) -> str:
    """Return a greeting."""
    return f"Hello, {name}"

def add(a: int, b: int) -> int:
    return a + b

class Calculator:
    def multiply(self, x: int, y: int) -> int:
        return x * y
'''

    def test_produces_chunks(self, chunker):
        chunks = chunker.chunk_file(self.SIMPLE_MODULE, "utils.py", "python", **COMMON_KWARGS)
        assert len(chunks) >= 2

    def test_chunk_types(self, chunker):
        chunks = chunker.chunk_file(self.SIMPLE_MODULE, "utils.py", "python", **COMMON_KWARGS)
        node_types = {c.node_type for c in chunks}
        assert "function" in node_types or "method" in node_types or "class" in node_types

    def test_function_names_extracted(self, chunker):
        chunks = chunker.chunk_file(self.SIMPLE_MODULE, "utils.py", "python", **COMMON_KWARGS)
        names = {c.node_name for c in chunks}
        assert "greet" in names or "add" in names

    def test_imports_prepended(self, chunker):
        chunks = chunker.chunk_file(self.SIMPLE_MODULE, "utils.py", "python", **COMMON_KWARGS)
        func_chunks = [c for c in chunks if c.node_type == "function"]
        for c in func_chunks:
            # imports_context or content should contain import block
            assert "import" in c.content or "import" in c.imports_context

    def test_line_numbers_set(self, chunker):
        chunks = chunker.chunk_file(self.SIMPLE_MODULE, "utils.py", "python", **COMMON_KWARGS)
        for c in chunks:
            assert c.start_line >= 1
            assert c.end_line >= c.start_line

    def test_rbac_fields_propagated(self, chunker):
        chunks = chunker.chunk_file(self.SIMPLE_MODULE, "utils.py", "python", **COMMON_KWARGS)
        for c in chunks:
            assert c.project_id == "proj-test"
            assert c.tenant_id == "tenant-1"
            assert c.allowed_roles == ["developer"]
            assert c.branch == "main"
            assert c.repository_name == "test-repo"

    def test_chunk_hash_set(self, chunker):
        chunks = chunker.chunk_file(self.SIMPLE_MODULE, "utils.py", "python", **COMMON_KWARGS)
        for c in chunks:
            assert len(c.chunk_hash) == 64

    def test_file_path_in_content(self, chunker):
        chunks = chunker.chunk_file(self.SIMPLE_MODULE, "utils/helpers.py", "python", **COMMON_KWARGS)
        for c in chunks:
            assert "utils/helpers.py" in c.content

    def test_class_and_methods(self, chunker):
        chunks = chunker.chunk_file(self.SIMPLE_MODULE, "calc.py", "python", **COMMON_KWARGS)
        method_chunks = [c for c in chunks if c.parent_class is not None]
        if method_chunks:
            assert method_chunks[0].parent_class == "Calculator"

    def test_secret_redacted_flag_propagated(self, chunker):
        chunks = chunker.chunk_file(
            self.SIMPLE_MODULE, "utils.py", "python",
            has_secrets_redacted=True,
            **COMMON_KWARGS,
        )
        for c in chunks:
            assert c.has_secrets_redacted is True


# ── JavaScript ────────────────────────────────────────────────────────────────

class TestJavaScriptChunking:
    JS_MODULE = '''
import { readFile } from 'fs';

function parseConfig(path) {
    return JSON.parse(readFile(path, 'utf8'));
}

const fetchData = async (url) => {
    const response = await fetch(url);
    return response.json();
};

class ApiClient {
    constructor(baseUrl) {
        this.baseUrl = baseUrl;
    }
    get(path) {
        return fetchData(this.baseUrl + path);
    }
}
'''

    def test_produces_chunks(self, chunker):
        chunks = chunker.chunk_file(self.JS_MODULE, "client.js", "javascript", **COMMON_KWARGS)
        assert len(chunks) >= 1

    def test_function_chunk_language(self, chunker):
        chunks = chunker.chunk_file(self.JS_MODULE, "client.js", "javascript", **COMMON_KWARGS)
        for c in chunks:
            assert c.language == "javascript"


# ── Fallback ──────────────────────────────────────────────────────────────────

class TestFallback:

    def test_unsupported_language_fallback(self, chunker):
        content = "SELECT * FROM users WHERE id = 1;"
        chunks = chunker.chunk_file(content, "query.sql", "sql", **COMMON_KWARGS)
        assert len(chunks) == 1
        assert chunks[0].node_type == "module"

    def test_empty_file_fallback(self, chunker):
        chunks = chunker.chunk_file("", "empty.py", "python", **COMMON_KWARGS)
        assert len(chunks) >= 1

    def test_syntax_error_fallback(self, chunker):
        # Deliberately broken Python
        broken = "def broken(\n    this is not valid python %%% @@@"
        chunks = chunker.chunk_file(broken, "broken.py", "python", **COMMON_KWARGS)
        # Should return at least one fallback chunk, not raise
        assert len(chunks) >= 1
