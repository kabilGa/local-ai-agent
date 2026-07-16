from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List
import httpx
import json

app = FastAPI(title="Model Gateway", version="1.0.0")

OLLAMA_URL = "http://localhost:11434"

class GenerateRequest(BaseModel):
    prompt: str
    model: str = "qwen2.5-coder:3b"
    temperature: float = 0.0
    max_tokens: int = 2048
    num_ctx: int = 8192

class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[Message]
    model: str = "qwen2.5-coder:3b"
    temperature: float = 0.0

class EmbeddingRequest(BaseModel):
    input: List[str]
    model: str = "nomic-embed-text"

@app.get("/health")
def health():
    return {"status": "ok"}

# ---------- GENERATE avec streaming ----------

@app.post("/v1/generate")
async def generate(req: GenerateRequest):
    async def stream_tokens():
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": req.model,
                    "prompt": req.prompt,
                    "stream": True,
                    "options": {"temperature": req.temperature, "num_ctx": req.num_ctx},
                },
            ) as response:
                async for line in response.aiter_lines():
                    if line.strip():
                        data = json.loads(line)
                        token = data.get("response", "")
                        if token:
                            yield f"data: {token}\n\n"
                yield "data: [DONE]\n\n"

    return StreamingResponse(stream_tokens(), media_type="text/event-stream")

# ---------- CHAT avec streaming ----------

@app.post("/v1/chat")
async def chat(req: ChatRequest):
    async def stream_tokens():
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": req.model,
                    "messages": [m.dict() for m in req.messages],
                    "stream": True,
                    "options": {"temperature": req.temperature},
                },
            ) as response:
                async for line in response.aiter_lines():
                    if line.strip():
                        data = json.loads(line)
                        token = data.get("message", {}).get("content", "")
                        if token:
                            yield f"data: {token}\n\n"
                yield "data: [DONE]\n\n"

    return StreamingResponse(stream_tokens(), media_type="text/event-stream")

# ---------- EMBEDDINGS (pas de streaming) ----------

@app.post("/v1/embeddings")
async def create_embeddings(req: EmbeddingRequest):
    embeddings = []
    async with httpx.AsyncClient(timeout=120.0) as client:
        for text in req.input:
            response = await client.post(
                f"{OLLAMA_URL}/api/embeddings",
                json={"model": req.model, "prompt": text},
            )
            data = response.json()
            embeddings.append(data.get("embedding", []))
    dimensions = len(embeddings[0]) if embeddings else 0
    return {"embeddings": embeddings, "model": req.model, "dimensions": dimensions}

# ---------- MODELS ----------

@app.get("/v1/models")
async def list_models():
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{OLLAMA_URL}/api/tags")
        data = response.json()
    return data.get("models", [])
# ============================================================================
# OpenAI-compatible chat completions endpoint  (added by Adam for integration)
# ----------------------------------------------------------------------------
# The orchestrator (Mehdi) calls POST /v1/chat/completions and reads the answer
# from choices[0].message.content (standard OpenAI shape, non-streaming).
# Mhamd's existing /v1/chat streams tokens, which the orchestrator can't parse,
# so this adds the non-streaming OpenAI endpoint the orchestrator needs.
# Mhamd's original endpoints are unchanged.
#
# --- FIX (Adam) ---
# The orchestrator hardcodes model "codellama", which is NOT an exact tag that
# Ollama has (we have qwen2.5-coder:* and codellama:7b-instruct-q4_K_M). An
# unknown model made Ollama return an error, this endpoint returned empty
# content, and the empty patch made the sandbox reject the request with 400.
# A Model Gateway should abstract models, so we map unknown/missing names to an
# available default, and we surface Ollama errors instead of returning "".
# ============================================================================

# Models this gateway actually has (see `ollama list`). First is the default.
AVAILABLE_MODELS = {
    "qwen2.5-coder:7b",
    "qwen2.5-coder:3b",
    "qwen2.5-coder:1.5b",
    "deepseek-coder:6.7b-instruct-q4_K_M",
    "codellama:7b-instruct-q4_K_M",
    "phi3:mini",
}
DEFAULT_MODEL = "qwen2.5-coder:7b"


def _resolve_model(requested: str | None) -> str:
    """Return an available Ollama model. Falls back to DEFAULT_MODEL if the
    requested name isn't an exact tag we have (e.g. 'codellama' with no tag)."""
    if requested and requested in AVAILABLE_MODELS:
        return requested
    # Try a loose match (e.g. 'codellama' -> 'codellama:7b-instruct-q4_K_M')
    if requested:
        for m in AVAILABLE_MODELS:
            if m.split(":")[0] == requested:
                return m
    return DEFAULT_MODEL


class ChatCompletionsRequest(BaseModel):
    messages: List[Message]
    model: str = DEFAULT_MODEL
    temperature: float = 0.0


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionsRequest):
    """OpenAI-compatible, non-streaming. Returns choices[0].message.content."""
    model = _resolve_model(req.model)

    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": model,
                "messages": [m.dict() for m in req.messages],
                "stream": False,  # single complete reply, not a stream
                "options": {"temperature": req.temperature},
            },
        )
        data = response.json()

    # Surface Ollama errors instead of silently returning empty content.
    if "error" in data:
        content = f"[Model Gateway error] Ollama: {data['error']}"
    else:
        content = data.get("message", {}).get("content", "")
        if not content.strip():
            content = "[Model Gateway error] Empty response from model."

    return {
        "id": "chatcmpl-local",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }