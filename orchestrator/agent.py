import os
import httpx
import re
import json
from langgraph.graph import StateGraph, END
from typing import TypedDict, List, Dict, Any

# Récupération des URLs des autres microservices (avec valeurs par défaut pour le local)
RAG_ENGINE_URL = os.getenv("RAG_ENGINE_URL", "http://localhost:8002/v1/retrieve")
MODEL_GATEWAY_URL = os.getenv("MODEL_GATEWAY_URL", "http://localhost:8003/v1/chat/completions")
SANDBOX_URL = os.getenv("SANDBOX_URL", "http://localhost:8004/v1/sandbox/execute")


def _extract_code(text: str, language: str = "python") -> str:
    """
    Extrait les blocs de code de la réponse du modèle (Spec 2.3).
    S'adapte dynamiquement à la langue cible (Python, Java, TypeScript/Angular, etc.).
    """
    if not text:
        return ""
    
    pairs = re.findall(r"^```(\w*)[ \t]*\r?\n(.*?)^```", text, re.DOTALL | re.MULTILINE)
    
    # Configuration des balises autorisées selon la langue détectée
    lang_lower = (language or "python").lower()
    allowed_tags = {"", lang_lower}
    
    if lang_lower in ("python", "py"):
        allowed_tags.update({"python", "py"})
    elif lang_lower in ("java", "spring-boot"):
        allowed_tags.update({"java", "xml", "properties", "yaml", "yml"})
    elif lang_lower in ("typescript", "ts", "angular", "javascript", "js"):
        allowed_tags.update({"typescript", "ts", "javascript", "js", "html", "css", "scss", "json"})

    blocks = [body for tag, body in pairs if tag.lower() in allowed_tags]
    if blocks:
        return "\n\n".join(b.strip() for b in blocks)
    
    return ""


# 1. Définition de l'état du Graphe (Mise à jour multi-langages Spec 2.1)
class AgentState(TypedDict):
    query: str
    project_id: str
    user_id: str
    context: str               # Rempli par le RAG
    code_patch: str            # Généré par le LLM
    verification_result: str   # Rempli par la Sandbox
    steps_track: List[Dict[str, Any]] # Pour l'exigence de traçabilité
    language: str              # Spec 2.1: "python", "java", "typescript", etc.
    framework: str             # Spec 2.1: "spring-boot", "angular", "none", etc.


# 2. NŒUD 0 : Détection de la Langue et du Framework (Spec 2.1)
async def detect_language(state: AgentState):
    steps = state.get("steps_track", [])
    try:
        system_prompt = (
            "You are a strict code language classifier. "
            "Analyze the user query and identify the requested programming language and framework. "
            "Respond ONLY with a valid JSON object matching this schema: "
            '{"language": "python" | "java" | "typescript", "framework": "spring-boot" | "angular" | "none"}. '
            "If no language is specified, default to: {\"language\": \"python\", \"framework\": \"none\"}."
        )
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            payload = {
                "model": "qwen2.5-coder:7b",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Query: {state['query']}"}
                ],
                "temperature": 0.0
            }
            response = await client.post(MODEL_GATEWAY_URL, json=payload)
            
            if response.status_code == 200:
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                cleaned = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                parsed = json.loads(cleaned)
                lang = parsed.get("language", "python").lower()
                fw = parsed.get("framework", "none").lower()
            else:
                lang, fw = "python", "none"
    except Exception as e:
        lang, fw = "python", "none"

    steps.append({
        "step_name": "Language_Detection", 
        "status": "SUCCESS", 
        "summary": f"Langue ciblée : {lang} (Framework: {fw})"
    })
    return {"language": lang, "framework": fw, "steps_track": steps}


# 3. NŒUD 1 : Appel au RAG Engine (Étudiant 4)
async def retrieve_code_context(state: AgentState):
    steps = state.get("steps_track", [])
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            payload = {
                "query": state["query"], 
                "user_id": state.get("user_id", "orchestrator"), 
                "project_ids": [state["project_id"]], 
                "allowed_roles": ["developer"], 
                "top_k": 5
            }
            response = await client.post(RAG_ENGINE_URL, json=payload)
            
            if response.status_code == 200:
                data = response.json()
                context = data.get("assembled_context", "Aucun code pertinent trouvé.")
                steps.append({"step_name": "RAG_Engine", "status": "SUCCESS", "summary": "Code source pertinent récupéré avec succès."})
                return {"context": context, "steps_track": steps}
            else:
                steps.append({"step_name": "RAG_Engine", "status": "FAILED", "summary": f"Erreur HTTP {response.status_code}"})
                return {"context": "", "steps_track": steps}
    except Exception as e:
        steps.append({"step_name": "RAG_Engine", "status": "CRITICAL_ERROR", "summary": str(e)})
        return {"context": "", "steps_track": steps}


# 4. NŒUD 2 : Appel au Model Gateway / LLM (Spec 2.4 & 2.7)
async def generate_code_patch(state: AgentState):
    steps = state["steps_track"]
    lang = state.get("language", "python")
    fw = state.get("framework", "none")

    try:
        # Prompt dynamique adaptable selon la langue et le framework détectés
        system_prompt = (
            f"You are an expert software development AI agent specializing in {lang} (Framework: {fw}). "
            "Analyze the provided source code and propose a fix (patch) "
            "as a clean code block to resolve the user's request. "
            "Always respond in English. "
            "Write any mathematical expressions using LaTeX: inline math "
            "between single dollar signs like $x^2$, and display math between "
            "double dollar signs like $$\\sum_{i=1}^{n} i$$."
        )
        user_prompt = f"Contexte du code source :\n{state['context']}\n\nDemande utilisateur : {state['query']}"
        
        async with httpx.AsyncClient(timeout=300.0) as client:
            payload = {
                "model": "qwen2.5-coder:7b",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.2
            }
            response = await client.post(MODEL_GATEWAY_URL, json=payload)
            
            if response.status_code == 200:
                data = response.json()
                patch = data["choices"][0]["message"]["content"]
                steps.append({"step_name": "Model_Gateway", "status": "SUCCESS", "summary": f"Patch de code ({lang}) généré par le LLM."})
                return {"code_patch": patch, "steps_track": steps}
            else:
                steps.append({"step_name": "Model_Gateway", "status": "FAILED", "summary": f"Erreur {response.status_code}"})
                return {"code_patch": "Erreur de génération.", "steps_track": steps}
    except Exception as e:
        steps.append({"step_name": "Model_Gateway", "status": "CRITICAL_ERROR", "summary": str(e)})
        return {"code_patch": "Échec de l'appel LLM.", "steps_track": steps}


# 5. NŒUD 3 : Appel à la Sandbox d'Exécution (Spec 2.2 & 2.6)
async def verify_patch_in_sandbox(state: AgentState):
    steps = state["steps_track"]
    lang = state.get("language", "python")
    
    # Si le patch a échoué précédemment, on saute la sandbox
    if "Erreur" in state["code_patch"] or "Échec" in state["code_patch"]:
        steps.append({"step_name": "Execution_Sandbox", "status": "SKIPPED", "summary": "Étape ignorée suite à une erreur précédente."})
        return {"verification_result": "Non testé", "steps_track": steps}
        
    try:
        # Timeout élevé (600s = 10 min) pour gérer les compilations lentes comme Maven ou npm (Spec 2.2)
        async with httpx.AsyncClient(timeout=600.0) as client:
            code_to_run = _extract_code(state["code_patch"], language=lang)
            if not code_to_run:
                steps.append({"step_name": "Execution_Sandbox", "status": "SKIPPED", "summary": "No matching code block in the answer - nothing to execute."})
                return {"verification_result": "No code to execute", "steps_track": steps}
            
            # Payload dynamique avec la langue (Spec 2.2)
            payload = {
                "code": code_to_run, 
                "language": lang,
                "framework": state.get("framework", "none")
            }
            response = await client.post(SANDBOX_URL, json=payload)
            
            if response.status_code == 200:
                data = response.json()
                result = data.get("stdout", "") or data.get("status", "Executed")
                steps.append({"step_name": "Execution_Sandbox", "status": "SUCCESS", "summary": f"Validation terminée ({lang}). Résultat: {result}"})
                return {"verification_result": result, "steps_track": steps}
            else:
                steps.append({"step_name": "Execution_Sandbox", "status": "FAILED", "summary": f"Erreur Sandbox {response.status_code}"})
                return {"verification_result": "Échec de l'exécution", "steps_track": steps}
    except Exception as e:
        steps.append({"step_name": "Execution_Sandbox", "status": "CRITICAL_ERROR", "summary": str(e)})
        return {"verification_result": "Erreur de connexion Sandbox", "steps_track": steps}


# =====================================================================
# 6. CONSTRUCTION ET COMPILATION DU GRAPH DE WORKFLOW
# =====================================================================
workflow = StateGraph(AgentState)

# Ajout des briques (nœuds)
workflow.add_node("detect_language", detect_language)
workflow.add_node("retrieve_context", retrieve_code_context)
workflow.add_node("generate_patch", generate_code_patch)
workflow.add_node("verify_patch", verify_patch_in_sandbox)

# Définition du cheminement (edges)
workflow.set_entry_point("detect_language")
workflow.add_edge("detect_language", "retrieve_context")
workflow.add_edge("retrieve_context", "generate_patch")
workflow.add_edge("generate_patch", "verify_patch")
workflow.add_edge("verify_patch", END)

# Compilation du graphe asynchrone
agent_orchestrator = workflow.compile()
