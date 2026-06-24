from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ── Retrieval ─────────────────────────────────────────────────────────────────

RETRIEVAL_LATENCY = Histogram(
    "rag_retrieval_duration_seconds",
    "End-to-end retrieval latency",
    ["cache_hit"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0],
)

RETRIEVAL_REQUESTS = Counter(
    "rag_retrieval_requests_total",
    "Total retrieval requests",
    ["status", "cache_hit"],
)

RETRIEVAL_CHUNKS_RETURNED = Histogram(
    "rag_retrieval_chunks_returned",
    "Number of chunks returned per retrieval",
    buckets=[1, 2, 3, 5, 10, 20],
)

# ── Indexing ──────────────────────────────────────────────────────────────────

INDEXING_JOBS = Counter(
    "rag_indexing_jobs_total",
    "Indexing jobs by status",
    ["status"],   # success | error | skipped
)

INDEXING_DURATION = Histogram(
    "rag_indexing_duration_seconds",
    "Full indexing job duration",
    buckets=[1, 5, 15, 30, 60, 120, 300, 600],
)

CHUNKS_INDEXED = Counter(
    "rag_chunks_indexed_total",
    "Total chunks indexed",
    ["language"],
)

FILES_INDEXED = Counter(
    "rag_files_indexed_total",
    "Total files indexed",
    ["language"],
)

FILES_SKIPPED = Counter(
    "rag_files_skipped_total",
    "Files skipped during indexing",
    ["reason"],   # too_large | excluded_extension | excluded_dir | parse_error
)

# ── Embedding ─────────────────────────────────────────────────────────────────

EMBEDDING_QUEUE_SIZE = Gauge(
    "rag_embedding_queue_size",
    "Current embedding queue depth",
)

EMBEDDING_BATCH_LATENCY = Histogram(
    "rag_embedding_batch_duration_seconds",
    "Embedding batch latency",
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0],
)

# ── Security ──────────────────────────────────────────────────────────────────

SECRETS_DETECTED = Counter(
    "rag_secrets_detected_total",
    "Secrets detected and redacted before indexing",
)

INJECTION_ATTEMPTS = Counter(
    "rag_injection_attempts_total",
    "Prompt injection patterns neutralised in retrieved content",
)

# ── Cache ─────────────────────────────────────────────────────────────────────

CACHE_HITS = Counter(
    "rag_cache_hits_total",
    "Semantic cache hits",
)

CACHE_MISSES = Counter(
    "rag_cache_misses_total",
    "Semantic cache misses",
)

# ── Infrastructure ────────────────────────────────────────────────────────────

QDRANT_COLLECTIONS = Gauge(
    "rag_qdrant_collections_total",
    "Number of active Qdrant collections",
)

ACTIVE_INDEX_JOBS = Gauge(
    "rag_active_index_jobs",
    "Currently running indexing jobs",
)

WEBHOOK_EVENTS = Counter(
    "rag_webhook_events_total",
    "Git webhook events received",
    ["event_type"],   # push | delete | merge_request
)
