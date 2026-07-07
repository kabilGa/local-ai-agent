from fastapi import FastAPI, status
from pydantic import BaseModel, Field
from typing import List, Dict, Any
from .agent import agent_orchestrator

app = FastAPI(
    title="Agent IA - Orchestrateur Complet",
    description="Microservice central orchestrant les requêtes à travers le RAG, le LLM et la Sandbox.",
    version="2.0.0"
)

# Contrat d'entrée venant de la Gateway (Étudiant 2)
class AgentChatRequest(BaseModel):
    message: str = Field(..., description="La consigne de l'utilisateur")
    project_id: str = Field(..., description="ID du projet pour le RAG")
    user_id: str = Field(..., description="ID de l'utilisateur pour l'audit")

# Contrat de sortie retourné à la Gateway pour affichage sur l'UI (Étudiant 1)
class AgentStepTrack(BaseModel):
    step_name: str
    status: str
    summary: str

class AgentChatResponse(BaseModel):
    response: str = Field(..., description="Le message explicatif final ou le patch de code corrigé")
    steps: List[AgentStepTrack] = Field(..., description="Historique d'exécution des outils (Exigence de traçabilité)")

@app.post(
    "/v1/agent/chat", 
    response_model=AgentChatResponse, 
    status_code=status.HTTP_200_OK
)
async def process_agent_logic(payload: AgentChatRequest):
    # 1. Initialisation de l'état du graphe avec les paramètres reçus
    initial_state = {
        "query": payload.message,
        "project_id": payload.project_id,
        "user_id": payload.user_id,
        "context": "",
        "code_patch": "",
        "verification_result": "",
        "steps_track": []
    }
    
    # 2. Lancement de l'orchestration (exécution asynchrone du graphe)
    final_state = await agent_orchestrator.ainvoke(initial_state)
    
    final_text = (
        f"{final_state['code_patch']}\n\n"
        f"**Sandbox verification:** {final_state['verification_result']}"
    )
    
    return AgentChatResponse(
        response=final_text,
        steps=final_state["steps_track"]
    )


# ── Streaming endpoint (Adam): emits progress after each graph node via SSE ────
import json
from fastapi.responses import StreamingResponse

@app.post("/v1/agent/stream")
async def process_agent_stream(payload: AgentChatRequest):
    initial_state = {
        "query": payload.message,
        "project_id": payload.project_id,
        "user_id": payload.user_id,
        "context": "",
        "code_patch": "",
        "verification_result": "",
        "steps_track": []
    }

    async def event_gen():
        last_len = 0
        final_state = None
        async for state in agent_orchestrator.astream(initial_state):
            # astream yields {node_name: state_after_node}
            for node_name, node_state in state.items():
                final_state = node_state
                steps = node_state.get("steps_track", [])
                # emit any new steps produced by this node
                while last_len < len(steps):
                    step = steps[last_len]
                    last_len += 1
                    yield f"data: {json.dumps({'type': 'step', 'step': step})}\n\n"
        # emit final response
        if final_state is not None:
            final_text = (
                f"{final_state.get('code_patch','')}\n\n"
                f"**Sandbox verification:** {final_state.get('verification_result','')}"
            )
            yield f"data: {json.dumps({'type': 'done', 'response': final_text})}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")
