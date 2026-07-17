import os
import httpx
from langgraph.graph import StateGraph, END
from typing import TypedDict, List, Dict, Any

# Récupération des URLs des autres microservices (avec valeurs par défaut pour le local)
import re

def _extract_code(text: str) -> str:
    """Pull only the code out of the model's reply.

    The model answers with prose + a fenced code block. Sending the whole
    reply to the sandbox makes it try to execute English as Python.
    """
    if not text:
        return ""
    pairs = re.findall(r"^```(\w*)[ \t]*\r?\n(.*?)^```", text, re.DOTALL | re.MULTILINE)
    blocks = [body for lang, body in pairs if lang.lower() in ("python", "py", "")]
    if blocks:
        return "\n\n".join(b.strip() for b in blocks)
    return ""


RAG_ENGINE_URL = os.getenv("RAG_ENGINE_URL", "http://localhost:8002/v1/retrieve")
MODEL_GATEWAY_URL = os.getenv("MODEL_GATEWAY_URL", "http://localhost:8003/v1/chat/completions")
SANDBOX_URL = os.getenv("SANDBOX_URL", "http://localhost:8004/v1/sandbox/execute")

# 1. Définition de l'état du Graphe (Données qui transitent d'étape en étape)
class AgentState(TypedDict):
    query: str
    project_id: str
    user_id: str
    context: str          # Rempli par le RAG
    code_patch: str       # Généré par le LLM
    verification_result: str # Rempli par la Sandbox
    attempts: int
    files_written: list   # Adam: files the agent created         # Adam: how many times the model has tried
    steps_track: List[Dict[str, Any]] # Pour l'exigence de traçabilité

# 2. NŒUD 1 : Appel au RAG Engine (Étudiant 4)
async def retrieve_code_context(state: AgentState):
    steps = state.get("steps_track", [])
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            payload = {"query": state["query"], "user_id": state.get("user_id", "orchestrator"), "project_ids": [state["project_id"]], "allowed_roles": ["developer"], "top_k": 5}
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

# 3. NŒUD 2 : Appel au Model Gateway / LLM (Étudiant 5)
async def generate_code_patch(state: AgentState):
    steps = state["steps_track"]
    try:
        # Construction du prompt technique incluant le contexte du RAG
        system_prompt = (
            "You are an expert software development AI agent. "
            "Analyze the provided source code and propose a fix (patch) "
            "as a clean code block to resolve the user's request. "
            "Always respond in English. "
            "Write any mathematical expressions using LaTeX: inline math "
            "between single dollar signs like $x^2$, and display math between "
            "double dollar signs like $$\\sum_{i=1}^{n} i$$. "
            "IF the user asks you to build, create, or make an application, a "
            "script, or a project, you MUST output the real files. Give one "
            "code block per file, and start each block with a marker line "
            "naming the path, exactly like this:\n"
            "# FILE: main.py\n"
            "Use relative paths only (never absolute, never '..'). Keep it "
            "simple and runnable with the Python standard library only. "
            "For pure questions or explanations, do NOT use FILE markers."
        )
        user_prompt = f"Contexte du code source :\n{state['context']}\n\nDemande utilisateur : {state['query']}"
        
        async with httpx.AsyncClient(timeout=300.0) as client:
            payload = {
                "model": "qwen2.5-coder:7b",  # Adam: was "codellama" - the gateway prefix-matched it to codellama:7b (a JS-heavy older model). Ask for the exact tag we want.
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.2
            }
            response = await client.post(MODEL_GATEWAY_URL, json=payload)
            
            if response.status_code == 200:
                data = response.json()
                # Extraction du message selon le standard OpenAI choisi par l'étudiant 5
                patch = data["choices"][0]["message"]["content"]
                steps.append({"step_name": "Model_Gateway", "status": "SUCCESS", "summary": "Patch de code généré par le LLM."})
                return {"code_patch": patch, "steps_track": steps}
            else:
                steps.append({"step_name": "Model_Gateway", "status": "FAILED", "summary": f"Erreur {response.status_code}"})
                return {"code_patch": "Erreur de génération.", "steps_track": steps}
    except Exception as e:
        steps.append({"step_name": "Model_Gateway", "status": "CRITICAL_ERROR", "summary": str(e)})
        return {"code_patch": "Échec de l'appel LLM.", "steps_track": steps}

# 4. NŒUD 3 : Appel à la Sandbox d'Exécution (Étudiant 6)
async def verify_patch_in_sandbox(state: AgentState):
    steps = state["steps_track"]
    # Si le patch a échoué précédemment, on saute la sandbox
    if "Erreur" in state["code_patch"] or "Échec" in state["code_patch"]:
        steps.append({"step_name": "Execution_Sandbox", "status": "SKIPPED", "summary": "Étape ignorée suite à une erreur précédente."})
        return {"verification_result": "Non testé", "steps_track": steps}
        
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            # On envoie le code généré à la sandbox pour validation (tests syntaxiques ou unitaires)
            code_to_run = _extract_code(state["code_patch"])
            if not code_to_run:
                steps.append({"step_name": "Execution_Sandbox", "status": "SKIPPED", "summary": "No code block in the answer - nothing to execute."})
                return {"verification_result": "No code to execute", "steps_track": steps}
            payload = {"code": code_to_run, "language": "python"}
            response = await client.post(SANDBOX_URL, json=payload)
            
            if response.status_code == 200:
                data = response.json()
                result = data.get("stdout", "") or data.get("status", "Executed")
                steps.append({"step_name": "Execution_Sandbox", "status": "SUCCESS", "summary": f"Validation terminée. Résultat: {result}"})
                return {"verification_result": result, "steps_track": steps}
            else:
                steps.append({"step_name": "Execution_Sandbox", "status": "FAILED", "summary": f"Erreur Sandbox {response.status_code}"})
                return {"verification_result": "Échec de l'exécution", "steps_track": steps}
    except Exception as e:
        steps.append({"step_name": "Execution_Sandbox", "status": "CRITICAL_ERROR", "summary": str(e)})
        return {"verification_result": "Erreur de connexion Sandbox", "steps_track": steps}

# =====================================================================
# 5. CONSTRUCTION ET COMPILATION DU GRAPH DE WORKFLOW
# =====================================================================
# ── Adam: file tools - lets the agent actually create an app on disk ──────────
AGENT_WORKSPACE = os.getenv("AGENT_WORKSPACE", "agent_workspace")

_FILE_MARKER = re.compile(r"^[#/;<!\-]{0,4}\s*FILE:\s*(.+?)\s*$", re.MULTILINE)


def _extract_files(text):
    """Pull out blocks that start with a '# FILE: path' marker."""
    from pathlib import PurePosixPath
    out = {}
    if not text:
        return out
    pairs = re.findall(r"^```(\w*)[ \t]*\r?\n(.*?)^```", text, re.DOTALL | re.MULTILINE)
    for _lang, body in pairs:
        m = _FILE_MARKER.search(body[:300])
        if not m:
            continue
        rel = m.group(1).strip().strip('`"\'')
        # reject anything that tries to escape the workspace
        pp = PurePosixPath(rel.replace("\\", "/"))
        if pp.is_absolute() or ".." in pp.parts or not pp.parts:
            continue
        out[str(pp)] = body[m.end():].lstrip("\r\n")
    return out


async def write_project_files(state):
    """Write the generated files into the agent workspace folder."""
    import os as _os
    steps = state["steps_track"]
    files = _extract_files(state.get("code_patch", ""))
    if not files:
        steps.append({"step_name": "Write_Files", "status": "SKIPPED",
                      "summary": "No '# FILE:' markers in the answer - nothing written."})
        return {"files_written": [], "steps_track": steps}
    root = _os.path.abspath(AGENT_WORKSPACE)
    written = []
    try:
        for rel, content in files.items():
            dest = _os.path.join(root, *rel.split("/"))
            if not _os.path.abspath(dest).startswith(root + _os.sep):
                continue
            _os.makedirs(_os.path.dirname(dest), exist_ok=True)
            with open(dest, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(content)
            written.append(rel)
        steps.append({"step_name": "Write_Files", "status": "SUCCESS",
                      "summary": "Wrote " + str(len(written)) + " file(s) to " + root + ": " + ", ".join(written)})
    except Exception as e:
        steps.append({"step_name": "Write_Files", "status": "CRITICAL_ERROR", "summary": str(e)})
    return {"files_written": written, "steps_track": steps}


MAX_ATTEMPTS = 2

_ERROR_MARKERS = ("Traceback", "SyntaxError", "NameError", "TypeError", "ValueError",
                  "ModuleNotFoundError", "IndentationError", "AssertionError",
                  "Exception", "Error:", "error:", "FAILED", "Echec", "Erreur")


async def prepare_retry(state: AgentState):
    """Adam: feed the sandbox error back to the model so it fixes its own code."""
    steps = state["steps_track"]
    attempts = state.get("attempts", 1) + 1
    error_text = (state.get("verification_result") or "")[:1500]
    commented = "\n".join("# " + ln for ln in error_text.splitlines())
    new_context = (
        state.get("context", "")
        + "\n\n# ---- YOUR PREVIOUS ATTEMPT FAILED ----\n"
        + "# The sandbox ran your last code and it failed with this error:\n"
        + commented
        + "\n# Fix it. Use only the Python standard library (no pip installs).\n"
        + "# Return the corrected, complete code in ONE python code block.\n"
    )
    steps.append({
        "step_name": "Retry_" + str(attempts),
        "status": "SUCCESS",
        "summary": "Attempt " + str(attempts - 1) + " failed - regenerating with the error as feedback.",
    })
    return {"context": new_context, "attempts": attempts, "steps_track": steps}


def should_retry(state: AgentState) -> str:
    """Loop back to the model if the sandbox failed and attempts remain."""
    result = state.get("verification_result") or ""
    attempts = state.get("attempts", 1)
    if "No code to execute" in result:
        return "end"
    if any(m in result for m in _ERROR_MARKERS) and attempts < MAX_ATTEMPTS:
        return "retry"
    return "end"


workflow = StateGraph(AgentState)

# Ajout des briques (nœuds)
workflow.add_node("retrieve_context", retrieve_code_context)
workflow.add_node("generate_patch", generate_code_patch)
workflow.add_node("verify_patch", verify_patch_in_sandbox)

# Définition du cheminement (edges)
workflow.set_entry_point("retrieve_context")
workflow.add_edge("retrieve_context", "generate_patch")
workflow.add_edge("generate_patch", "verify_patch")
workflow.add_node("prepare_retry", prepare_retry)

# Adam: was a straight line (verify -> END), so the agent never fixed its own
# mistakes. Now the sandbox error loops back into the model.
workflow.add_conditional_edges(
    "verify_patch",
    should_retry,
    {"retry": "prepare_retry", "end": "write_files"},
)
workflow.add_edge("prepare_retry", "generate_patch")
workflow.add_node("write_files", write_project_files)
workflow.add_edge("write_files", END)

# Compilation du graphe asynchrone
agent_orchestrator = workflow.compile()