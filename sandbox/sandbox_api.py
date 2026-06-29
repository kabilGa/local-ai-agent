"""
sandbox_api.py — API HTTP pour le service Sandbox
Traduit le contrat de l'orchestrateur {"code", "language"} -> exécution
sécurisée dans la sandbox Docker (réseau coupé, read-only, non-root,
allowlist d'interpréteurs) puis renvoie {"status", "stdout"}.

Exigences CDC couvertes : SEC-11, SEC-12, SEC-13, SEC-25, T-11

--- NOTE D'INTÉGRATION (Adam) ---
3 ajustements pour brancher ce service à l'orchestrateur de Mehdi.
La logique de sécurité d'origine est inchangée :
  1. Port 8003 -> 8004  (8003 est réservé au Model Gateway ; l'orch appelle la sandbox sur 8004)
  2. Route /execute -> /v1/sandbox/execute  (chemin attendu par l'orchestrateur)
  3. Import 'from sandbox_runner' -> 'from .sandbox_runner'  (structure de package du repo)
"""

import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .sandbox_runner import log, masquer_secrets

app = FastAPI(title="Sandbox Service", version="1.0")

MAX_CODE_SIZE = 200_000  # ~200 KB, anti-abus simple

# --------------------------------------------------------------------------
# Docker-in-Docker via socket monté : le "docker run" lancé plus bas est
# exécuté par le daemon de l'HÔTE (pas par ce conteneur). Un chemin créé
# avec tempfile à l'intérieur de CE conteneur n'existe pas pour le daemon
# hôte -> il faut un dossier partagé, monté au même endroit sur l'hôte et
# sur ce conteneur, et donner au "docker run" le chemin côté HÔTE.
#
# CONTAINER_WORKSPACE_ROOT : où CE conteneur voit le dossier partagé
#                            (doit correspondre au volume docker-compose,
#                            ex: ./shared_workspace:/shared_workspace)
# HOST_WORKSPACE_ROOT      : où l'hôte Windows voit ce même dossier
#                            (ex: C:\Users\fedit\Desktop\sandbox-project\shared_workspace)
#                            -> vient de la variable d'environnement
#                            HOST_WORKSPACE_PATH définie dans docker-compose.yml
# --------------------------------------------------------------------------
CONTAINER_WORKSPACE_ROOT = Path("/shared_workspace")
HOST_WORKSPACE_ROOT = os.environ.get("HOST_WORKSPACE_PATH", "").rstrip("\\/")

if not HOST_WORKSPACE_ROOT:
    log("warning", "host_workspace_path_non_defini")

LANGUAGE_IMAGES = {
    "python": "sandbox-python:local",
    "javascript": "sandbox-node:local",
    "node": "sandbox-node:local",
}

LANGUAGE_EXT = {
    "python": "py",
    "javascript": "js",
    "node": "js",
}

EXEC_TIMEOUT = 30


class CodeExecutionRequest(BaseModel):
    code: str
    language: Literal["python", "javascript", "node"] = "python"


class CodeExecutionResponse(BaseModel):
    status: str
    stdout: str


@app.post("/v1/sandbox/execute", response_model=CodeExecutionResponse)
def execute_code(req: CodeExecutionRequest) -> CodeExecutionResponse:
    """
    Reçoit du code généré par l'IA, l'écrit dans un sous-dossier éphémère
    du workspace partagé, puis le passe à l'interpréteur correspondant à
    l'intérieur d'un container Docker durci : réseau coupé, filesystem
    read-only, non-root, capacités Linux supprimées, CPU/RAM/temps limités.

    On n'utilise jamais `exec()` ni `sh -c` sur du texte fourni par
    l'IA : le fichier est monté en lecture seule et c'est l'interpréteur
    (python / node) qui le lit, dans un bac à sable qui ne peut rien
    atteindre à l'extérieur de lui-même.
    """
    run_id = str(uuid.uuid4())[:8]

    if not req.code or not req.code.strip():
        raise HTTPException(status_code=400, detail="Le champ 'code' est vide.")

    if len(req.code.encode("utf-8")) > MAX_CODE_SIZE:
        log("warning", "code_trop_volumineux", run_id=run_id, taille=len(req.code))
        raise HTTPException(status_code=413, detail="Code trop volumineux.")

    image = LANGUAGE_IMAGES.get(req.language)
    ext = LANGUAGE_EXT.get(req.language)
    if image is None:
        raise HTTPException(status_code=400, detail=f"Langage '{req.language}' non supporté.")

    log("info", "code_recu", run_id=run_id, langage=req.language,
        taille_octets=len(req.code.encode("utf-8")))

    # Sous-dossier dédié à ce run, créé sous le dossier partagé.
    # Vu par CE conteneur :   /shared_workspace/run_<id>
    # Vu par le host (Windows) : HOST_WORKSPACE_ROOT\run_<id>
    run_dirname = f"run_{run_id}"
    workspace_container_path = CONTAINER_WORKSPACE_ROOT / run_dirname
    workspace_host_path = f"{HOST_WORKSPACE_ROOT}\\{run_dirname}" if HOST_WORKSPACE_ROOT else None

    try:
        workspace_container_path.mkdir(parents=True, exist_ok=False)
        script_name = f"submitted_code.{ext}"
        (workspace_container_path / script_name).write_text(req.code, encoding="utf-8")

        if workspace_host_path is None:
            log("error", "host_workspace_path_manquant", run_id=run_id)
            return CodeExecutionResponse(
                status="Failed",
                stdout="Configuration serveur incomplète : HOST_WORKSPACE_PATH non défini.",
            )

        resultat = _executer_snippet(image, req.language, script_name, workspace_host_path, run_id)
    finally:
        shutil.rmtree(workspace_container_path, ignore_errors=True)

    status = "Executed" if resultat["succes"] else "Failed"
    stdout_final = masquer_secrets(resultat["stdout"] or resultat["stderr"])

    log("info", "execution_terminee", run_id=run_id, status=status)

    return CodeExecutionResponse(status=status, stdout=stdout_final)


def _executer_snippet(image: str, language: str, script_name: str,
                       workspace_host_path: str, run_id: str) -> dict:
    interpreteur = ["python", script_name] if language == "python" else ["node", script_name]
    container_name = f"sandbox_snippet_{run_id}"

    commande_docker = [
        "docker", "run", "--rm",
        "--name", container_name,
        "--network", "none",                         # SEC-12
        "--read-only",                                # SEC-11
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m",
        "--user", "10001:10001",
        "--security-opt", "no-new-privileges:true",
        "--cap-drop", "ALL",
        "--cpus", "0.5",
        "--memory", "256m",
        "--memory-swap", "256m",
        # IMPORTANT : ce "docker run" est exécuté par le daemon de l'HÔTE
        # (via le socket monté), donc le chemin à gauche du ":" doit être
        # un chemin compris par l'hôte, pas par ce conteneur.
        "--volume", f"{workspace_host_path}:/workspace:ro",
        "--workdir", "/workspace",
        image,
        *interpreteur,
    ]

    try:
        resultat = subprocess.run(
            commande_docker, capture_output=True, text=True, timeout=EXEC_TIMEOUT
        )
        return {
            "succes": resultat.returncode == 0,
            "stdout": resultat.stdout,
            "stderr": resultat.stderr,
        }
    except subprocess.TimeoutExpired:
        log("error", "timeout_expire_snippet", run_id=run_id)
        subprocess.run(["docker", "stop", container_name], capture_output=True, timeout=10)
        subprocess.run(["docker", "rm", "--force", container_name], capture_output=True, timeout=10)
        return {"succes": False, "stdout": "", "stderr": f"Timeout ({EXEC_TIMEOUT}s) dépassé."}
    except FileNotFoundError:
        log("error", "docker_introuvable", run_id=run_id)
        return {"succes": False, "stdout": "", "stderr": "Docker non trouvé."}


@app.get("/health")
def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004)
