from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

from .models import CodeChunk

logger = logging.getLogger(__name__)

# ── Node type sets ────────────────────────────────────────────────────────────

CHUNK_NODE_TYPES: frozenset[str] = frozenset({
    # Python
    "function_definition", "async_function_definition", "class_definition",
    # JavaScript / TypeScript
    "function_declaration", "function_expression", "arrow_function",
    "method_definition", "class_declaration", "class_expression",
    "lexical_declaration",          # const fn = () => …
    # Java
    "method_declaration", "constructor_declaration",
    "class_declaration", "interface_declaration", "enum_declaration",
    # Go
    "function_declaration", "method_declaration", "type_declaration",
    # Rust
    "function_item", "impl_item", "struct_item", "enum_item", "trait_item",
    "type_alias",
})

IMPORT_NODE_TYPES: frozenset[str] = frozenset({
    "import_statement", "import_from_statement",   # Python
    "import_declaration",                           # JS / TS / Java
    "use_declaration",                              # Rust
    "import_spec",                                  # Go
    "require",                                      # CommonJS-style
})

CLASS_NODE_TYPES: frozenset[str] = frozenset({
    "class_definition", "class_declaration", "class_expression",
    "impl_item",
})


# ── Parser registry ───────────────────────────────────────────────────────────

def _build_parser_registry() -> Dict[str, object]:
    """Load tree-sitter parsers; skip any that fail to load."""
    registry: Dict[str, object] = {}
    try:
        from tree_sitter import Language, Parser
    except ImportError:
        logger.error("tree-sitter not installed — AST chunking disabled")
        return registry

    def _load(lang_key: str, module_name: str, lang_fn: str, aliases: list[str] = []):
        try:
            mod = __import__(module_name)
            lang = Language(getattr(mod, lang_fn)())
            p = Parser(lang)
            registry[lang_key] = p
            for alias in aliases:
                registry[alias] = p
        except Exception as exc:
            logger.warning("Parser '%s' not available: %s", lang_key, exc)

    _load("python", "tree_sitter_python", "language")
    _load("javascript", "tree_sitter_javascript", "language", ["jsx"])
    _load("typescript", "tree_sitter_typescript", "language_typescript", ["tsx"])
    _load("java", "tree_sitter_java", "language")
    _load("go", "tree_sitter_go", "language")
    _load("rust", "tree_sitter_rust", "language")

    loaded = list(registry.keys())
    logger.info("Tree-sitter parsers loaded: %s", loaded)
    return registry


_REGISTRY: Dict[str, object] | None = None


def _get_parser(language: str):
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_parser_registry()
    return _REGISTRY.get(language)


# ── ASTChunker ────────────────────────────────────────────────────────────────

class ASTChunker:
    """
    Chunk source files by AST node boundaries using Tree-sitter.
    Chunking by character count or line count is explicitly prohibited
    (RAG Engine Guide §2.2).
    """

    def chunk_file(
        self,
        file_content: str,
        file_path: str,
        language: str,
        *,
        project_id: str = "",
        tenant_id: str = "",
        allowed_roles: Optional[List[str]] = None,
        sensitivity_level: str = "internal",
        commit_hash: str = "unknown",
        branch: str = "main",
        repository_name: str = "",
        has_secrets_redacted: bool = False,
    ) -> List[CodeChunk]:
        """Parse a source file and return a list of CodeChunks."""
        roles = allowed_roles or []
        common = dict(
            file_path=file_path,
            language=language,
            project_id=project_id,
            tenant_id=tenant_id,
            allowed_roles=roles,
            sensitivity_level=sensitivity_level,
            commit_hash=commit_hash,
            branch=branch,
            repository_name=repository_name,
            has_secrets_redacted=has_secrets_redacted,
        )

        parser = _get_parser(language)
        if parser is None:
            return [self._whole_file_chunk(file_content, **common)]

        try:
            tree = parser.parse(file_content.encode("utf-8", errors="replace"))
        except Exception as exc:
            logger.warning("Parse failed for %s (%s): %s", file_path, language, exc)
            return [self._whole_file_chunk(file_content, **common)]

        imports_block = self._extract_imports(tree.root_node, file_content)
        chunks: List[CodeChunk] = []
        self._visit(
            tree.root_node, file_content, imports_block, chunks,
            parent_class=None, **common,
        )

        return chunks if chunks else [self._whole_file_chunk(file_content, **common)]

    # ── Tree traversal ────────────────────────────────────────────────────────

    def _visit(
        self,
        node,
        source: str,
        imports: str,
        chunks: List[CodeChunk],
        *,
        parent_class: Optional[str],
        **common,
    ) -> None:
        if node.type not in CHUNK_NODE_TYPES:
            for child in node.children:
                self._visit(child, source, imports, chunks,
                            parent_class=parent_class, **common)
            return

        raw = source[node.start_byte:node.end_byte]
        name = self._extract_name(node, source)
        is_class = node.type in CLASS_NODE_TYPES
        node_type = "class" if is_class else "function"
        # Methods inside a class get node_type="method"
        if not is_class and parent_class:
            node_type = "method"

        full_content = (
            f"{imports}\n\n# --- {common['file_path']} ---\n{raw}"
            if imports else
            f"# --- {common['file_path']} ---\n{raw}"
        )

        chunk = CodeChunk(
            content=full_content,
            node_type=node_type,
            node_name=name,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            parent_class=parent_class,
            imports_context=imports,
            docstring=self._extract_docstring(node, source),
            calls=self._collect_calls(node, source),
            imports=self._parse_import_names(imports),
            chunk_hash=_normalize_hash(full_content),
            **common,
        )
        chunks.append(chunk)

        # Recurse into classes to find methods
        next_parent = name if is_class else parent_class
        for child in node.children:
            self._visit(child, source, imports, chunks,
                        parent_class=next_parent, **common)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_imports(root_node, source: str) -> str:
        lines = []
        for node in root_node.children:
            if node.type in IMPORT_NODE_TYPES:
                lines.append(source[node.start_byte:node.end_byte])
        return "\n".join(lines)

    @staticmethod
    def _extract_name(node, source: str) -> str:
        for child in node.children:
            if child.type in ("identifier", "name", "property_identifier"):
                return source[child.start_byte:child.end_byte]
        return "anonymous"

    @staticmethod
    def _extract_docstring(node, source: str) -> Optional[str]:
        """Best-effort docstring extraction from the first statement."""
        for child in node.children:
            if child.type in ("block", "statement_block", "body"):
                for stmt in child.children:
                    for inner in stmt.children:
                        if inner.type in ("string", "string_literal"):
                            raw = source[inner.start_byte:inner.end_byte]
                            return raw.strip("'\"` ")
        return None

    @classmethod
    def _collect_calls(cls, node, source: str) -> List[str]:
        calls: set[str] = set()
        cls._recurse_calls(node, source, calls)
        return list(calls)

    @classmethod
    def _recurse_calls(cls, node, source: str, acc: set) -> None:
        if node.type == "call":
            func = node.children[0] if node.children else None
            if func:
                name = source[func.start_byte:func.end_byte].split("(")[0].strip()
                if name and len(name) < 80 and not name.startswith('"'):
                    acc.add(name)
        for child in node.children:
            cls._recurse_calls(child, source, acc)

    @staticmethod
    def _parse_import_names(imports_block: str) -> List[str]:
        names = re.findall(r"(?:import|from)\s+([a-zA-Z_][a-zA-Z0-9_.]*)", imports_block)
        return list(dict.fromkeys(names))   # deduplicated, order-preserving

    @staticmethod
    def _whole_file_chunk(content: str, **common) -> CodeChunk:
        """Fallback: index the entire file as one chunk."""
        lines = content.splitlines()
        file_path = common.get("file_path", "")
        return CodeChunk(
            content=f"# --- {file_path} ---\n{content}",
            node_type="module",
            node_name=Path(file_path).stem or "file",
            start_line=1,
            end_line=len(lines),
            chunk_hash=_normalize_hash(content),
            **common,
        )


def _normalize_hash(content: str) -> str:
    """SHA-256 of whitespace-normalised content — used for deduplication."""
    normalised = " ".join(content.split())
    return hashlib.sha256(normalised.encode()).hexdigest()
