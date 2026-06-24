# RAG Engine — Code Search

Local Retrieval-Augmented Generation engine for the AI coding/debugging/security agent.
Implements the full technical spec from `RAG_ENGINE_GUIDE.md` and `Cahier_des_charges_Agent_IA_Local.docx`.

---

## Architecture

```
Orchestrateur ──► POST /v1/retrieve ──► HybridSearcher
                                            │
                                ┌───────────┼───────────┐
                                │           │           │
                           Dense Search  BM25 Search  Symbol Graph
                           (Qdrant)      (rank-bm25)  (NetworkX/Redis)
                                │           │           │
                                └───────────┴───────────┘
                                            │
                                       RRF Fusion
                                            │
                                    Optional Reranker
                                            │
                                   ContextAssembler
                                   (anti-injection)
                                            │
                                  RetrieveResponse
                               (context + source refs)
```

**The RAG engine does NOT:**
- Run LLM inference (that is the Model Gateway)
- Execute code (that is the Sandbox)
- Authenticate users (that is the API Gateway)

---

## Quick start

```bash
# 1. Clone and configure
cp .env.example .env
# Edit .env with your values

# 2. Start infrastructure
cd docker
docker compose --env-file ../.env up -d
cd ..

# 3. Install Python deps
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 4. Run the API
python -m rag.api.main
# → http://localhost:8000/docs
```

---

## Triggering indexation

```bash
# Index a repository
curl -X POST http://localhost:8000/v1/index \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "my-service",
    "repository_url": "https://github.com/org/repo.git",
    "git_token": "ghp_...",
    "branch": "main",
    "tenant_id": "team-backend",
    "allowed_roles": ["developer", "security"]
  }'

# Poll job status
curl http://localhost:8000/v1/index/status/<job_id>
```

---

## Querying

```bash
curl -X POST http://localhost:8000/v1/retrieve \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Where is the user authentication logic?",
    "user_id": "u-123",
    "project_ids": ["my-service"],
    "allowed_roles": ["developer"],
    "top_k": 5
  }'
```

Response includes:
- `assembled_context` — ready to inject into the LLM prompt
- `sources` — exact file/line references for anti-hallucination
- `cache_hit` — whether result came from semantic cache

---

## Running tests

```bash
# Unit tests only (no infrastructure needed)
pytest tests/unit/ -v

# Integration tests (requires Qdrant running)
pytest tests/integration/ -v -m integration
```

---

## Key security properties

| Property | Implementation |
|---|---|
| Secrets never indexed | `SecretScanner` runs before every chunk |
| RBAC isolation | Qdrant filter on `project_id` + `allowed_roles` on every query |
| Prompt injection | `ContextAssembler._sanitize()` neutralises patterns before LLM |
| No cross-tenant leaks | Semantic cache keyed by RBAC hash |
| Read-only Git | `GitConnector` never calls push |
| Air-gapped support | `fastembed` local mode, no external calls |

---

## CDC compliance mapping

| CDC ID | Requirement | Implementation |
|---|---|---|
| IDX-01 | Authorised repos only | `project_id` + `allowed_roles` filter |
| IDX-03 | Incremental indexation | `IncrementalIndexer` + webhook |
| IDX-04 | Isolated per project/tenant | One Qdrant collection per project |
| IDX-06 | Purge verifiable | `DELETE /v1/index/{project_id}` |
| QAI-06 | Anti-prompt injection | `ContextAssembler._sanitize()` |
| SEC-14 | Prompt injection detection | Regex patterns on retrieved content |
| F-07 | Sourced responses | `sources` field in every response |
| AI-10 | No training on client code | No outbound calls, no fine-tuning pipeline |

---

## Development phases

| Phase | Status | Target |
|---|---|---|
| Phase 1 — Dense search MVP | ✅ Complete | Recall@5 ≥ 70% |
| Phase 2 — Hybrid search + reranker | ✅ Complete | Recall@5 ≥ 85% |
| Phase 3 — Symbol graph + cache | ✅ Complete | Recall@5 ≥ 95%, P95 ≤ 5s |
| Phase 4 — Production hardening | 🔧 See docker/ | LUKS, mTLS, SBOM |
