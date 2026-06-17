"""
API Gateway - the single entry point for the Local AI Agent.

Responsibilities:
  - receive all client requests
  - validate input
  - (later) authenticate + rate-limit
  - route to the correct backend service
  - log every request
  - return a unified response

Run:  uvicorn gateway.main:app --reload --port 8000
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException
from shared.models import AgentRequest, AgentResponse

app = FastAPI(
    title="Local AI Agent - Gateway",
    description="Single entry point that routes requests to backend services",
    version="0.1.0",
)


@app.get("/health")
def health():
    return {"status": "ok", "service": "gateway"}


@app.post("/agent", response_model=AgentResponse)
def agent(request: AgentRequest):
    """
    Main entry point. For now it just echoes back - wiring to the
    router / rag / sandbox / security services comes next.
    """
    if not request.prompt or not request.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")

    # TODO: route to backend services (router -> rag -> model -> etc.)
    return AgentResponse(
        answer=f"[gateway placeholder] received: {request.prompt}",
        success=True,
    )
