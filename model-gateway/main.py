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