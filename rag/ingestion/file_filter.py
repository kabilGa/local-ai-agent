from __future__ import annotations

from pathlib import Path

# ── Excluded binary / generated extensions ────────────────────────────────────
EXCLUDED_EXTENSIONS: frozenset[str] = frozenset({
    ".exe", ".dll", ".so", ".dylib", ".class", ".pyc", ".pyo", ".pyd",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar", ".tgz",
    ".jar", ".war", ".ear", ".whl", ".egg",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
    ".mp4", ".mp3", ".wav", ".avi", ".mov", ".mkv",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".map",  # source maps
    ".lock",  # lockfiles — large, low RAG value
})

# Partial suffix matches (ends-with)
EXCLUDED_SUFFIX_PATTERNS: tuple[str, ...] = (
    ".min.js",
    ".min.css",
    ".bundle.js",
    ".d.ts",   # TypeScript declaration files — no logic
)

# ── Excluded directories ──────────────────────────────────────────────────────
EXCLUDED_DIRS: frozenset[str] = frozenset({
    "node_modules", ".git", "__pycache__", "vendor",
    ".venv", "venv", ".env",
    "dist", "build", "out", "target", "bin", "obj",
    ".idea", ".vscode", ".eclipse",
    "coverage", ".nyc_output", ".pytest_cache",
    "migrations",   # DB migration files can be huge
    "fixtures",
    "__snapshots__",
})

# ── Supported languages ───────────────────────────────────────────────────────
SUPPORTED_LANGUAGES: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".tf": "terraform",
    ".hcl": "hcl",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".sql": "sql",
    ".md": "markdown",
    ".rst": "text",
    ".txt": "text",
    ".env.example": "text",
    ".env.sample": "text",
}

NAMED_FILES: dict[str, str] = {
    "Dockerfile": "dockerfile",
    "Makefile": "makefile",
    "Rakefile": "ruby",
    "Gemfile": "ruby",
    "Pipfile": "toml",
    "Cargo.toml": "toml",
    "go.mod": "go",
    "go.sum": "text",
    "pyproject.toml": "toml",
    "setup.py": "python",
    "setup.cfg": "text",
}

MAX_FILE_SIZE_BYTES: int = 500_000  # 500 KB per spec


def should_index_file(path: Path) -> bool:
    """Return True iff this file should be indexed."""
    # Excluded directories in path hierarchy
    for part in path.parts:
        if part in EXCLUDED_DIRS:
            return False

    # Named file check (Dockerfile, Makefile…)
    if path.name in NAMED_FILES:
        return True

    # Size check
    try:
        if path.stat().st_size > MAX_FILE_SIZE_BYTES:
            return False
    except OSError:
        return False

    # Partial suffix patterns (.min.js etc.)
    name_lower = path.name.lower()
    if any(name_lower.endswith(p) for p in EXCLUDED_SUFFIX_PATTERNS):
        return False

    suffix = path.suffix.lower()
    if not suffix:
        return False

    return suffix not in EXCLUDED_EXTENSIONS and suffix in SUPPORTED_LANGUAGES


def get_language(path: Path) -> str | None:
    """Return the language identifier for a file, or None if unsupported."""
    if path.name in NAMED_FILES:
        return NAMED_FILES[path.name]
    suffix = path.suffix.lower()
    return SUPPORTED_LANGUAGES.get(suffix)
