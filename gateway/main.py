"""
API Gateway - the single entry point for the Local AI Agent.

The "front desk" of the whole system. Every request goes through here.
It serves the user web page, validates requests, remembers conversation
history (so the agent doesn't forget context), routes to the right backend
service, logs everything, and always returns a clean response.

Run:  uvicorn gateway.main:app --reload --port 8000
User page:  http://localhost:8000
API menu:   http://localhost:8000/docs
"""

import sys, os, time, json, logging
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException, Request, Header, Depends
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
from shared.models import AgentResponse
from gateway.clients import call_router, call_rag, call_sandbox, call_security, rag_available
from gateway import memory
from gateway import auth

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "gateway.log", mode="a", encoding="utf-8"),
    ],
)
log = logging.getLogger("gateway")


def audit(event: str, **details):
    entry = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "event": event, **details}
    with open(LOG_DIR / "audit.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


app = FastAPI(
    title="Local AI Agent - Gateway",
    description="Single entry point that routes requests to backend services",
    version="1.2.0",
)

# Warn loudly if authentication is running in open mode (no keys configured).
if not auth.AUTH_ENABLED:
    log.warning("AUTH is OPEN (no GATEWAY_API_KEYS set). Set keys to require authentication.")


# ── Security guard: authentication + quota, used by protected endpoints ───────
def require_auth(x_api_key: str | None = Header(default=None)):
    """
    FastAPI dependency that protects an endpoint:
      1. checks the API key (authentication)
      2. checks the per-identity request quota (rate limiting)
    Attach it to an endpoint with: dependencies=[Depends(require_auth)]
    or use it as a parameter to read the identity.
    """
    # 1. Authentication
    if not auth.check_api_key(x_api_key):
        audit("auth_rejected", reason="invalid_or_missing_api_key")
        raise HTTPException(status_code=401, detail="Invalid or missing API key (X-API-Key header)")

    # 2. Quota (keyed by the API key, or 'anonymous' in open mode)
    identity = x_api_key or "anonymous"
    allowed, remaining = auth.check_quota(identity)
    if not allowed:
        audit("quota_exceeded", identity_preview=identity[:8])
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded ({auth.MAX_REQUESTS} requests per {auth.WINDOW_SECONDS}s). Try again shortly.",
        )
    return identity


# ── Request model: now includes a session_id for memory ───────────────────────
class AgentRequest(BaseModel):
    prompt: str
    session_id: str | None = None
    repo_name: str | None = None


# ── Middleware: time + log every request, never crash ─────────────────────────
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    try:
        response = await call_next(request)
    except Exception as e:
        duration = round((time.time() - start) * 1000)
        log.error(f"UNHANDLED {request.method} {request.url.path} after {duration}ms: {e}")
        return JSONResponse(status_code=500,
            content={"success": False, "error": "Internal gateway error", "detail": str(e)})
    duration = round((time.time() - start) * 1000)
    log.info(f"{request.method} {request.url.path} -> {response.status_code} ({duration}ms)")
    return response


# ── User web page ─────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def home():
    html_path = Path(__file__).parent.parent / "frontend" / "index.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return "<h1>Frontend not found</h1>"


@app.get("/health")
def health():
    return {"status": "ok", "service": "gateway", "version": "1.1.0"}


@app.get("/router/models")
def router_models():
    """Pass-through so the web page can show the tier->model mapping."""
    try:
        from router.classifier import MODEL_TIERS, ESTIMATED_LATENCY
        return {t: {"model": m, "estimated_latency_s": ESTIMATED_LATENCY.get(t, 0)}
                for t, m in MODEL_TIERS.items()}
    except Exception:
        return {}


@app.get("/services/status")
def services_status():
    return {
        "router":   call_router("ping").success,
        "rag":      rag_available(),
        "sandbox":  call_sandbox("python", "version").success,
        "security": call_security("dummy").success,
    }


@app.get("/gateway/config")
def gateway_config():
    """Show the gateway's security configuration (auth + quotas), no secrets leaked."""
    return {**auth.auth_status(), **auth.quota_status()}


# ── Clear a conversation (new chat) ───────────────────────────────────────────
@app.post("/session/clear")
def clear_session(session_id: str):
    memory.clear_session(session_id)
    return {"cleared": session_id}


# ── Main endpoint: ask the agent, WITH memory ─────────────────────────────────
@app.post("/agent", response_model=AgentResponse)
def agent(request: AgentRequest, identity: str = Depends(require_auth)):
    prompt = (request.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")
    if len(prompt) > 10000:
        raise HTTPException(status_code=400, detail="Prompt too long (max 10000 characters)")

    session_id = request.session_id or "default"
    audit("agent_request", session=session_id, prompt_preview=prompt[:80])
    log.info(f"[{session_id}] Agent request: {prompt[:60]}...")

    # 1. RAG context (skips gracefully if not built)
    rag_result = call_rag(prompt, request.repo_name)
    context_chunks = []
    if rag_result.success and rag_result.data:
        context_chunks = rag_result.data.get("chunks", [])

    # 2. Build the prompt WITH conversation history (this is the memory part)
    prompt_with_memory = memory.build_prompt_with_history(session_id, prompt)

    # 3. Route to the model
    router_result = call_router(prompt_with_memory)

    if not router_result.success:
        log.error(f"Router failed: {router_result.error}")
        audit("agent_failed", reason=router_result.error)
        return AgentResponse(answer="", success=False,
            error=router_result.error or "The model router is unavailable. Is Ollama running?")

    data = router_result.data
    answer = data.get("answer", "")

    # 4. Save BOTH sides to memory so the next message has context
    memory.add_message(session_id, "user", prompt)
    memory.add_message(session_id, "assistant", answer)

    audit("agent_answered", session=session_id, model=data.get("model_used"),
          tier=data.get("tier"), latency_s=data.get("latency_s"))

    return AgentResponse(
        answer=answer,
        model_used=data.get("model_used"),
        tier=data.get("tier"),
        sources=context_chunks or None,
        latency_s=data.get("latency_s"),
        success=True,
    )


# ── Streaming endpoint ────────────────────────────────────────────────────────
# The cahier des charges asks for response streaming (answers appearing
# progressively, like modern chat assistants). This endpoint streams the
# model's answer back token-by-token using Server-Sent Events (SSE).
#
# It classifies the prompt to pick a model, then asks Ollama to stream the
# generation, forwarding each chunk to the client as it arrives.

import httpx
from router.classifier import classify_to_dict

OLLAMA_URL = "http://localhost:11434/api/generate"


@app.post("/agent/stream")
def agent_stream(request: AgentRequest, identity: str = Depends(require_auth)):
    """Stream the answer back progressively (Server-Sent Events)."""
    prompt = (request.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")

    session_id = request.session_id or "default"
    decision = classify_to_dict(prompt)
    model = decision["model"]
    prompt_with_memory = memory.build_prompt_with_history(session_id, prompt)
    audit("agent_stream_request", session=session_id, model=model)

    def event_stream():
        # First, tell the client which model/tier was chosen
        yield f"data: {json.dumps({'type': 'meta', 'model': model, 'tier': decision['tier']})}\n\n"
        full_answer = ""
        try:
            with httpx.stream("POST", OLLAMA_URL, json={
                "model": model, "prompt": prompt_with_memory, "stream": True,
                "options": {"temperature": 0.2},
            }, timeout=300) as resp:
                for line in resp.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    piece = chunk.get("response", "")
                    if piece:
                        full_answer += piece
                        yield f"data: {json.dumps({'type': 'token', 'text': piece})}\n\n"
                    if chunk.get("done"):
                        break
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
            return
        # Save to memory and signal completion
        memory.add_message(session_id, "user", prompt)
        memory.add_message(session_id, "assistant", full_answer)
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── Orchestrator-compatible endpoint ──────────────────────────────────────────
# The orchestrator (Étudiant 3) sends {"message","project_id","user_id"} and
# expects {"response","steps"} back. This endpoint speaks that exact contract,
# while reusing the same routing + memory logic as /agent. Both endpoints
# coexist: the web page uses /agent, the orchestrator uses /v1/agent/chat.

class OrchestratorRequest(BaseModel):
    message: str
    project_id: str | None = None
    user_id: str | None = None


class OrchestratorResponse(BaseModel):
    response: str
    steps: list = []


@app.post("/v1/agent/chat", response_model=OrchestratorResponse)
def agent_chat(request: OrchestratorRequest, identity: str = Depends(require_auth)):
    """Orchestrator-facing endpoint. Accepts the orchestrator's JSON shape."""
    message = (request.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message cannot be empty")
    if len(message) > 10000:
        raise HTTPException(status_code=400, detail="message too long (max 10000 characters)")

    # Use user_id as the memory session so each user keeps their own history.
    session_id = request.user_id or "orchestrator"
    audit("orchestrator_request", session=session_id, project=request.project_id,
          preview=message[:80])
    log.info(f"[orchestrator:{session_id}] {message[:60]}...")

    # Same flow as /agent: RAG context -> memory -> route to model
    rag_result = call_rag(message, request.project_id)
    context_chunks = []
    if rag_result.success and rag_result.data:
        context_chunks = rag_result.data.get("chunks", [])

    prompt_with_memory = memory.build_prompt_with_history(session_id, message)
    router_result = call_router(prompt_with_memory)

    if not router_result.success:
        log.error(f"Router failed: {router_result.error}")
        audit("orchestrator_failed", reason=router_result.error)
        # Return the orchestrator's shape even on error
        return OrchestratorResponse(
            response=router_result.error or "The model router is unavailable.",
            steps=[],
        )

    data = router_result.data
    answer = data.get("answer", "")

    memory.add_message(session_id, "user", message)
    memory.add_message(session_id, "assistant", answer)

    # "steps" describes what the gateway did, in the orchestrator's expected
    # list form. The gateway performs a single routing step (it is not itself
    # the multi-step agent loop), so we report that one step transparently.
    steps = [{
        "step": "route_and_generate",
        "model_used": data.get("model_used"),
        "tier": data.get("tier"),
        "rag_context_used": len(context_chunks) > 0,
        "latency_s": data.get("latency_s"),
    }]

    audit("orchestrator_answered", session=session_id,
          model=data.get("model_used"), tier=data.get("tier"))

    return OrchestratorResponse(response=answer, steps=steps)


# ── VS Code extension-compatible endpoints ────────────────────────────────────
# The VS Code extension (frontend/vscode-extension) talks to the gateway using
# its own contract (paths under /api/, field names message/project/conversationId).
# These adapters speak that contract while reusing the same routing + memory
# logic, so the extension works without changing the extension's code.

class ChatRequest(BaseModel):
    message: str
    project: str | None = None
    explainMode: str | None = None
    conversationId: str | None = None


class ChatResponse(BaseModel):
    response: str
    conversationId: str
    sources: list | None = None
    patch: dict | None = None


@app.post("/api/chat", response_model=ChatResponse)
def api_chat(request: ChatRequest, identity: str = Depends(require_auth)):
    """Chat endpoint in the VS Code extension's expected shape."""
    message = (request.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message cannot be empty")

    # Use the conversationId as the memory session, or make a stable default.
    session_id = request.conversationId or f"vscode-{request.project or 'default'}"
    audit("api_chat_request", session=session_id, project=request.project,
          preview=message[:80])

    # RAG context (skips gracefully if not built)
    rag_result = call_rag(message, request.project)
    context_chunks = []
    if rag_result.success and rag_result.data:
        context_chunks = rag_result.data.get("chunks", [])

    prompt_with_memory = memory.build_prompt_with_history(session_id, message)
    router_result = call_router(prompt_with_memory)

    if not router_result.success:
        audit("api_chat_failed", reason=router_result.error)
        return ChatResponse(
            response=router_result.error or "The model router is unavailable. Is Ollama running?",
            conversationId=session_id,
        )

    answer = router_result.data.get("answer", "")
    memory.add_message(session_id, "user", message)
    memory.add_message(session_id, "assistant", answer)
    audit("api_chat_answered", session=session_id,
          model=router_result.data.get("model_used"))

    # Map RAG chunks into the extension's "sources" shape if any exist.
    sources = None
    if context_chunks:
        sources = [{
            "file": c.get("file", "unknown"),
            "lineStart": c.get("line_start", 0),
            "lineEnd": c.get("line_end", 0),
            "snippet": c.get("snippet", ""),
        } for c in context_chunks]

    return ChatResponse(response=answer, conversationId=session_id, sources=sources)


@app.get("/api/projects")
def api_projects():
    """List projects. The gateway is repo-agnostic for now, so it returns a
    single default project. (Project management belongs to the orchestrator/portal.)"""
    return [{
        "id": "default",
        "name": "Local Project",
        "repo": "local",
        "branch": "main",
    }]


@app.post("/api/security/scan")
def api_security_scan(payload: dict, identity: str = Depends(require_auth)):
    """Security scan in the extension's expected shape. Routes to the security
    service; returns a graceful empty result until that service is built."""
    target = payload.get("file") or payload.get("project") or "workspace"
    result = call_security(target)
    if not result.success:
        # Graceful: security/SAST service not built yet.
        return {
            "findings": [],
            "summary": "Security scanning is not available yet (the SAST/SCA service is not built).",
            "scannedFiles": 0,
        }
    return result.data


# ── Direct service endpoints (light up when teammates finish) ─────────────────
@app.post("/scan")
def scan(file_path: str):
    result = call_security(file_path)
    if not result.success:
        raise HTTPException(status_code=503, detail=result.error or "Security service unavailable")
    return result.data


@app.post("/run")
def run(tool: str, command: str, workspace_path: str = "./workspace"):
    """
    Run an allow-listed command in the sandbox.
      tool:    "python", "node", or "security"
      command: the command to run (must be on the sandbox's allowlist)
    Requires Docker on the host running the sandbox.
    """
    result = call_sandbox(tool, command, workspace_path)
    if not result.success:
        raise HTTPException(status_code=503, detail=result.error or "Sandbox service unavailable")
    return result.data
