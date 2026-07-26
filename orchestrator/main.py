import uvicorn
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

# Import de ton agent compilé depuis agent.py
from agent import agent_orchestrator

app = FastAPI(
    title="Orchestrator Microservice",
    description="Microservice d'orchestration LangGraph pour la génération et validation multi-langages de code.",
    version="2.0.0"
)

# Configuration CORS pour autoriser la communication inter-services
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =====================================================================
# MODÈLES PYDANTIC (Contrats d'entrée et de sortie)
# =====================================================================

class AgentRequest(BaseModel):
    message: str = Field(..., description="Message ou problème soumis par l'utilisateur", example="Mon controller Spring Boot renvoie une erreur 500")
    project_id: str = Field(..., description="Identifiant du projet", example="proj_123")
    user_id: Optional[str] = Field("student_user", description="Identifiant de l'utilisateur")
    language: Optional[str] = Field(None, description="Langue optionnelle forcée par la Gateway")


class AgentResponse(BaseModel):
    response: str = Field(..., description="Patch de code ou réponse générée par le LLM")
    verification_result: str = Field(..., description="Résultat d'exécution renvoyé par la Sandbox")
    language: str = Field(..., description="Langue identifiée/utilisée (python, java, typescript)")
    framework: str = Field(..., description="Framework identifié (spring-boot, angular, none)")
    steps: List[Dict[str, Any]] = Field(..., description="Traçabilité détaillée des étapes du workflow")


# =====================================================================
# ROUTES API
# =====================================================================

@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check():
    """Vérification de l'état de santé du service."""
    return {"status": "healthy", "service": "orchestrator", "version": "2.0.0"}


@app.post("/v1/agent/chat", response_model=AgentResponse, status_code=status.HTTP_200_OK)
async def chat_with_agent(payload: AgentRequest):
    """
    Point d'entrée principal appelé par la Gateway.
    Orchestre le RAG, le LLM et la Sandbox via LangGraph.
    """
    try:
        # Construction de l'état initial pour LangGraph
        initial_state = {
            "query": payload.message,
            "project_id": payload.project_id,
            "user_id": payload.user_id,
            "context": "",
            "code_patch": "",
            "verification_result": "",
            "steps_track": [],
            "language": payload.language or "python",
            "framework": "none"
        }

        # Exécution asynchrone du workflow LangGraph
        final_state = await agent_orchestrator.ainvoke(initial_state)

        # Extraction et retour du résultat
        return AgentResponse(
            response=final_state.get("code_patch", "Aucune réponse générée."),
            verification_result=final_state.get("verification_result", "Non exécuté."),
            language=final_state.get("language", "python"),
            framework=final_state.get("framework", "none"),
            steps=final_state.get("steps_track", [])
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur interne dans l'Orchestrateur: {str(e)}"
        )


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
