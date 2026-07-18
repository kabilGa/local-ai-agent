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
    files_written: list
    staged_files: dict     # Adam: files awaiting user confirmation
    plan: list            # Adam: the planned file list
    current_step: int     # Adam: which file we are on   # Adam: files the agent created         # Adam: how many times the model has tried
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
    # Adam: models often put the marker just ABOVE the fence - pull it inside.
    text = re.sub(r"(?m)^[#/;<!\-]{0,4}[ \t]*FILE:[ \t]*(.+?)[ \t]*\r?\n\s*```(\w*)[ \t]*\r?\n",
                  lambda m: "```" + m.group(2) + "\n# FILE: " + m.group(1) + "\n", text)
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


def apply_files_to_disk(files):
    """Adam: the ACTUAL write - called only after the user confirms."""
    import os as _os
    root = _os.path.abspath(AGENT_WORKSPACE)
    written = []
    for rel, content in files.items():
        dest = _os.path.join(root, *rel.split("/"))
        if not _os.path.abspath(dest).startswith(root + _os.sep):
            continue
        _os.makedirs(_os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        written.append(rel)
    return written, root


async def write_project_files(state):
    """Adam: human-in-the-loop (cahier des charges 3.2). We do NOT write here.
    We STAGE the files and wait for the user to confirm. The actual write
    happens in apply_files_to_disk via the /v1/agent/apply endpoint."""
    steps = state["steps_track"]
    files = _extract_files(state.get("code_patch", ""))
    if not files:
        steps.append({"step_name": "Write_Files", "status": "SKIPPED",
                      "summary": "No '# FILE:' markers in the answer - nothing to write."})
        return {"staged_files": {}, "files_written": [], "steps_track": steps}
    steps.append({"step_name": "Write_Files", "status": "PENDING",
                  "summary": "Ready to write " + str(len(files)) + " file(s): "
                             + ", ".join(files.keys()) + " - awaiting your confirmation."})
    return {"staged_files": files, "files_written": [], "steps_track": steps}


MAX_ATTEMPTS = 2

_ERROR_MARKERS = ("Traceback", "SyntaxError", "NameError", "TypeError", "ValueError",
                  "ModuleNotFoundError", "IndentationError", "AssertionError",
                  "Exception", "Error:", "error:", "FAILED", "Echec", "Erreur")


# ── Adam: planner - build multi-file projects one file at a time ─────────────
_BUILD_WORDS = ("build", "create", "make me", "generate", "app", "application",
                "project", "database", "system", "script for")

PLANNER_MODEL = os.getenv("PLANNER_MODEL", "qwen2.5-coder:7b")
STEP_MODEL = os.getenv("STEP_MODEL", "qwen2.5-coder:7b")  # Adam: 3b wrote files that did not fit together


def _looks_like_build(query):
    q = (query or "").lower()
    return any(w in q for w in _BUILD_WORDS)


def route_after_retrieve(state):
    """Build request -> planner. Question -> the normal single-pass path."""
    return "plan" if _looks_like_build(state.get("query", "")) else "single"


async def _ask_model(model, system, user, timeout=300.0):
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(MODEL_GATEWAY_URL, json={
            "model": model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": 0.0,
        })
        if resp.status_code != 200:
            raise RuntimeError("Model gateway HTTP " + str(resp.status_code))
        return resp.json()["choices"][0]["message"]["content"]


async def plan_project(state):
    """First pass: decide WHICH files to write, no code yet."""
    import json as _json
    steps = state["steps_track"]
    system = ("You are a software architect. Break the request into a small list "
              "of files. Return ONLY a JSON array - no prose, no markdown fences. "
              "Each item must be {\"file\": \"relative/path.py\", \"purpose\": \"one sentence\"}. "
              "Maximum 4 files. Relative paths only. Python standard library only.")
    try:
        raw = await _ask_model(PLANNER_MODEL, system, "Request: " + state["query"])
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        plan = _json.loads(m.group(0)) if m else []
        plan = [x for x in plan if isinstance(x, dict) and x.get("file")][:4]
    except Exception as e:
        steps.append({"step_name": "Planner", "status": "FAILED", "summary": str(e)[:200]})
        return {"plan": [], "current_step": 0, "steps_track": steps}
    if not plan:
        steps.append({"step_name": "Planner", "status": "SKIPPED",
                      "summary": "No usable plan - falling back to single file."})
        return {"plan": [], "current_step": 0, "steps_track": steps}
    names = ", ".join(x["file"] for x in plan)
    steps.append({"step_name": "Planner", "status": "SUCCESS",
                  "summary": "Plan: " + str(len(plan)) + " file(s) - " + names})
    return {"plan": plan, "current_step": 0, "code_patch": "", "steps_track": steps}


async def generate_step(state):
    """Write ONE file, with the previously written files in context."""
    import json as _json
    steps = state["steps_track"]
    plan = state.get("plan", [])
    i = state.get("current_step", 0)
    if i >= len(plan):
        return {"steps_track": steps}
    item = plan[i]
    fname = item.get("file", "main.py")
    so_far = state.get("code_patch", "")
    system = ("You are an expert Python developer. Write ONE file only. "
              "Start with the marker line '# FILE: " + fname + "' then the code "
              "in a single python code block. No explanation before or after. "
              "Python standard library only.\n"
              "RULES - a reviewer will reject the file if you break these:\n"
              "1. IMPORT EVERY MODULE YOU USE. If you write math.sin you must "
              "have 'import math' at the top of THIS file. Check every name.\n"
              "2. Only call functions that actually exist in the files already "
              "written. Match their exact signatures. Do not invent methods.\n"
              "3. Do not redefine anything already defined in another file.\n"
              "4. Write complete, working code - no placeholders or TODOs.\n"
              "5. Re-read your file before finishing: would it run as-is?\n"
              "6. The FIRST line inside the code block MUST be exactly: # FILE: " + fname)
    user = ("Project request: " + state["query"] + "\n\nFull plan: " + _json.dumps(plan)
            + "\n\nFiles written so far:\n" + (so_far[:4000] if so_far else "(none yet)")
            + "\n\nNow write ONLY: " + fname + "\nPurpose: " + str(item.get("purpose", "")))
    try:
        content = await _ask_model(STEP_MODEL, system, user)
        steps.append({"step_name": "Build_" + str(i + 1) + ": " + fname,
                      "status": "SUCCESS", "summary": "Generated " + fname})
        return {"code_patch": (so_far + "\n\n" + content).strip(),
                "current_step": i + 1, "steps_track": steps}
    except Exception as e:
        steps.append({"step_name": "Build_" + str(i + 1) + ": " + fname,
                      "status": "FAILED", "summary": str(e)[:200]})
        return {"current_step": i + 1, "steps_track": steps}


async def check_files(state):

    """Adam: compile each generated file and report undefined names.

    The sandbox cannot import tkinter, so this is the only real feedback."""

    import ast as _ast

    steps = state["steps_track"]

    files = _extract_files(state.get("code_patch", ""))

    problems = []

    for name, src in files.items():

        try:

            tree = _ast.parse(src)

        except SyntaxError as e:

            problems.append(name + ": SyntaxError line " + str(e.lineno) + " - " + str(e.msg))

            continue

        imported = set()

        for n in _ast.walk(tree):

            if isinstance(n, _ast.Import):

                imported.update(a.asname or a.name.split(".")[0] for a in n.names)

            elif isinstance(n, _ast.ImportFrom):

                imported.update(a.asname or a.name for a in n.names)

        used = {n.value.id for n in _ast.walk(tree)

                if isinstance(n, _ast.Attribute) and isinstance(n.value, _ast.Name)}
        # Adam: also catch bare use like {"math": math}, not just math.sin
        used |= {n.id for n in _ast.walk(tree)
                 if isinstance(n, _ast.Name) and isinstance(n.ctx, _ast.Load)}

        assigned = {n.id for n in _ast.walk(tree)

                    if isinstance(n, _ast.Name) and isinstance(n.ctx, _ast.Store)}

        assigned |= {n.name for n in _ast.walk(tree)

                     if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef))}

        args = {a.arg for n in _ast.walk(tree)

                if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))

                for a in n.args.args}

        for mod in ("math", "os", "sys", "json", "random", "time", "sqlite3", "re"):

            if mod in used and mod not in imported and mod not in assigned and mod not in args:

                problems.append(name + ": uses '" + mod + "' but never imports it")

        # Adam: signature check - catch calls with too few/many args across files
        import ast as _ast2
        defs = {}
        for _src in files.values():
            try:
                _t = _ast2.parse(_src)
            except SyntaxError:
                continue
            for _n in _ast2.walk(_t):
                if isinstance(_n, (_ast2.FunctionDef, _ast2.AsyncFunctionDef)):
                    _req = len(_n.args.args) - len(_n.args.defaults)
                    _tot = len(_n.args.args)
                    defs[_n.name] = (_req, _tot, _n.args.vararg is not None)
        for _name, _src in files.items():
            try:
                _t = _ast2.parse(_src)
            except SyntaxError:
                continue
            for _n in _ast2.walk(_t):
                if isinstance(_n, _ast2.Call) and isinstance(_n.func, _ast2.Name):
                    _fn = _n.func.id
                    if _fn in defs and not _n.keywords:
                        _req, _tot, _star = defs[_fn]
                        _given = len(_n.args)
                        _self = 1 if ("self" not in [a for a in []] ) else 0
                        if _given < _req or (not _star and _given > _tot):
                            problems.append(_name + ": calls " + _fn + "() with " + str(_given)
                                            + " args but it needs " + str(_req) + "-" + str(_tot))
    if problems:

        steps.append({"step_name": "Code_Check", "status": "FAILED",

                      "summary": "; ".join(problems[:4])})

    else:

        steps.append({"step_name": "Code_Check", "status": "SUCCESS",

                      "summary": "All " + str(len(files)) + " file(s) compile, imports look complete."})

    return {"verification_result": ("CODE CHECK FAILED: " + "; ".join(problems)) if problems else "checks passed",

            "steps_track": steps}

async def rebuild_with_errors(state):
    """Adam: the checker found broken files - rebuild them with the errors."""
    steps = state["steps_track"]
    attempts = state.get("attempts", 1) + 1
    errs = (state.get("verification_result") or "")[:1200]
    new_ctx = (state.get("context", "")
               + "\n\n# ---- YOUR LAST BUILD WAS REJECTED ----\n# "
               + errs.replace("\n", "\n# ")
               + "\n# Fix every one of these. Import every module you use.\n")
    steps.append({"step_name": "Rebuild_" + str(attempts),
                  "status": "SUCCESS",
                  "summary": "Code check failed - rebuilding with the errors as feedback."})
    return {"context": new_ctx, "attempts": attempts, "current_step": 0,
            "code_patch": "", "steps_track": steps}


def build_ok(state):
    r = state.get("verification_result") or ""
    if "CODE CHECK FAILED" in r and state.get("attempts", 1) < MAX_ATTEMPTS:
        return "rebuild"
    return "ok"


def more_steps(state):
    return "next" if state.get("current_step", 0) < len(state.get("plan", [])) else "done"


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
    # Adam: never retry an environment limit - the sandbox is headless and
    # read-only, so tkinter/GUI/file errors are not the model's fault.
    if any(k in result for k in ("libtk", "_tkinter", "no display name",
                                 "DISPLAY", "unable to open database file",
                                 "Read-only file system")):
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
workflow.add_node("plan_project", plan_project)
workflow.add_node("generate_step", generate_step)

# Adam: build requests go through the planner and are generated file by file.
# Questions keep the old single-pass path.
workflow.add_conditional_edges("retrieve_context", route_after_retrieve,
                               {"plan": "plan_project", "single": "generate_patch"})
workflow.add_conditional_edges("plan_project",
                               lambda st: "step" if st.get("plan") else "single",
                               {"step": "generate_step", "single": "generate_patch"})
workflow.add_conditional_edges("generate_step", more_steps,
                               {"next": "generate_step", "done": "check_files"})
workflow.add_node("verify_build", verify_patch_in_sandbox)
workflow.add_node("check_files", check_files)
workflow.add_node("rebuild_with_errors", rebuild_with_errors)
workflow.add_conditional_edges("check_files", build_ok,
                               {"rebuild": "rebuild_with_errors", "ok": "write_files"})
workflow.add_edge("rebuild_with_errors", "generate_step")
workflow.add_edge("verify_build", "write_files")
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