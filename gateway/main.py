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

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from shared.models import AgentResponse
from gateway.clients import call_router, call_rag, call_sandbox, call_security, rag_available
from gateway import memory

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
    version="1.1.0",
)


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


# ── Clear a conversation (new chat) ───────────────────────────────────────────
@app.post("/session/clear")
def clear_session(session_id: str):
    memory.clear_session(session_id)
    return {"cleared": session_id}


# ── Main endpoint: ask the agent, WITH memory ─────────────────────────────────
@app.post("/agent", response_model=AgentResponse)
def agent(request: AgentRequest):
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
