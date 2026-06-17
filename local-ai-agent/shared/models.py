"""
Shared data models used across all services.
Everyone imports request/response shapes from here so the
gateway and the backend services always agree on the format.
"""

from pydantic import BaseModel
from typing import Optional, Any


class AgentRequest(BaseModel):
    """A request coming in from a client (UI, CLI)."""
    prompt: str
    session_id: Optional[str] = None
    repo_name: Optional[str] = None


class AgentResponse(BaseModel):
    """A unified response sent back to the client."""
    answer: str
    model_used: Optional[str] = None
    tier: Optional[str] = None
    sources: Optional[list[dict]] = None
    latency_s: Optional[float] = None
    success: bool = True
    error: Optional[str] = None


class ServiceResult(BaseModel):
    """Internal result passed between gateway and a backend service."""
    service: str
    data: Any
    success: bool = True
    error: Optional[str] = None
