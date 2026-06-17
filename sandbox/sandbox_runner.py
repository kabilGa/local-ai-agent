"""
runner.py — Sandbox sécurisé v3
Ajouts : pids-limit (détection OS), pip-audit, checkov
"""

import json
import logging
import logging.handlers
import platform
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal


# ── Secret masking (SEC-25) ───────────────────────────────────
SECRET_PATTERNS = [
    (re.compile(r'(api[_-]?key\s*[=:]\s*)\S+',     re.IGNORECASE), r'\1***'),
    (re.compile(r'(token\s*[=:]\s*)\S+',            re.IGNORECASE), r'\1***'),
    (re.compile(r'(password\s*[=:]\s*)\S+',         re.IGNORECASE), r'\1***'),
    (re.compile(r'(secret\s*[=:]\s*)\S+',           re.IGNORECASE), r'\1***'),
    (re.compile(r'(Authorization:\s*Bearer\s*)\S+', re.IGNORECASE), r'\1***'),
    (re.compile(r'ghp_[A-Za-z0-9]{36}'),                            '***'),
    (re.compile(r'sk-[A-Za-z0-9]{48}'),                             '***'),
    (re.compile(r'AKIA[A-Z0-9]{16}'),                               '***'),
]

def masquer_secrets(texte: str) -> str:
    for pattern, repl in SECRET_PATTERNS:
        texte = pattern.sub(repl, texte)
    return texte


# ── Logger SIEM rotatif (SEC-09) ─────────────────────────────
def _setup_logger() -> logging.Logger:
    logger = logging.getLogger("sandbox")
    logger.setLevel(logging.DEBUG)
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(console)
    log_dir = Path("./logs")
    log_dir.mkdir(exist_ok=True)
    fh = logging.handlers.RotatingFileHandler(
        log_dir / "sandbox.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    fh.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(fh)
    return logger

_logger = _setup_logger()

def log(level: str, event: str, **kwargs):
    kwargs_masques = {k: masquer_secrets(v) if isinstance(v, str) else v for k, v in kwargs.items()}
    record = {"ts": datetime.now(timezone.utc).isoformat(), "level": level, "event": event, **kwargs_masques}
    getattr(_logger, level.lower(), _logger.info)(json.dumps(record, ensure_ascii=False))


# ── Détection OS pour pids-limit (SEC-11) ────────────────────
# --pids-limit non supporté sur Docker Desktop Windows
IS_LINUX = platform.system() == "Linux"


# ── Allowlist (SEC-13) ────────────────────────────────────────
ALLOWLIST: dict[tuple[str, str], list[str]] = {
    # Python
    ("python",   "pytest"):            ["python", "-m", "pytest", "--tb=short", "-q"],
    ("python",   "lint"):              ["python", "-m", "flake8", "--max-line-length=120"],
    ("python",   "format-check"):      ["python", "-m", "black", "--check", "."],
    ("python",   "bandit"):            ["python", "-m", "bandit", "-r", "-f", "json", "."],
    ("python",   "pip-audit"):         ["pip-audit", "--format", "json"],

    # Node.js
    ("node",     "jest"):              ["jest", "--passWithNoTests"],
    ("node",     "eslint"):            ["eslint", "--format", "json", "."],
    ("node",     "prettier-check"):    ["prettier", "--check", "."],

    # Sécurité (APPSEC-02)
    ("security", "semgrep"):           ["semgrep", "scan", "--config", "auto", "--json"],
    ("security", "bandit-scan"):       ["bandit", "-r", "-f", "json", "."],
    ("security", "detect-secrets"):    ["detect-secrets", "scan", "."],
    ("security", "pip-audit"):         ["pip-audit", "--format", "json"],
    ("security", "checkov"):           ["checkov", "-d", ".", "--quiet", "--compact"],
}

TOOL_IMAGES: dict[str, str] = {
    "python":   "sandbox-python:local",
    "node":     "sandbox-node:local",
    "security": "sandbox-security:local",
}

# Codes normaux — l'outil a tourné mais a trouvé des issues
CODES_OK: dict[tuple[str, str], list[int]] = {
    ("python",   "lint"):           [0, 1],
    ("python",   "bandit"):         [0, 1],
    ("python",   "pip-audit"):      [0, 1],
    ("security", "bandit-scan"):    [0, 1],
    ("security", "semgrep"):        [0, 1],
    ("security", "detect-secrets"): [0, 1],
    ("security", "pip-audit"):      [0, 1],
    ("security", "checkov"):        [0, 1],
}

TIMEOUT_SECONDS = 60


# ── Fonction principale ───────────────────────────────────────
def executer_dans_sandbox(
    outil: Literal["python", "node", "security"],
    commande: str,
    workspace_path: str = "./workspace"
) -> dict:
    run_id = str(uuid.uuid4())[:8]
    cle = (outil, commande)

    # Vérification allowlist (SEC-13)
    if cle not in ALLOWLIST:
        log("warning", "commande_refusee", run_id=run_id, outil=outil, commande=commande,
            raison="hors allowlist",
            autorisees=str([c for (o, c) in ALLOWLIST if o == outil]))
        return {"run_id": run_id, "succes": False, "stdout": "",
                "stderr": f"Commande '{commande}' non autorisée pour '{outil}'.",
                "code_retour": -1}

    cmd_outil = ALLOWLIST[cle]
    image = TOOL_IMAGES[outil]
    workspace_abs = str(Path(workspace_path).resolve())
    container_name = f"sandbox_{run_id}"

    # Construction commande Docker
    commande_docker = [
        "docker", "run", "--rm",
        "--name", container_name,
        "--network", "none",                        # SEC-12
        "--read-only",                              # SEC-11
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev",
        "--user", "10001:10001",
        "--security-opt", "no-new-privileges:true",
        "--cap-drop", "ALL",
        "--cpus", "1.0",
        "--memory", "512m",
        "--memory-swap", "512m",
        "--volume", f"{workspace_abs}:/workspace:ro",
        "--workdir", "/workspace",
    ]

    # pids-limit : Linux uniquement (Docker Desktop Windows ne le supporte pas)
    if IS_LINUX:
        commande_docker += ["--pids-limit", "50"]

    commande_docker += [image, *cmd_outil]

    log("info", "job_demarre", run_id=run_id, outil=outil, commande=commande,
        image=image, timeout=TIMEOUT_SECONDS,
        pids_limit="50" if IS_LINUX else "desactive_windows")

    try:
        resultat = subprocess.run(
            commande_docker, capture_output=True, text=True, timeout=TIMEOUT_SECONDS
        )

        if resultat.returncode == 125:
            stderr_masque = masquer_secrets(resultat.stderr.strip())
            log("error", "docker_erreur_125", run_id=run_id, stderr=stderr_masque[:400])
            return {"run_id": run_id, "succes": False, "stdout": "",
                    "stderr": resultat.stderr.strip(), "code_retour": 125}

        codes_acceptes = CODES_OK.get(cle, [0])
        succes = resultat.returncode in codes_acceptes

        log("info" if succes else "warning", "job_termine",
            run_id=run_id, outil=outil, commande=commande,
            code_retour=resultat.returncode, succes=succes)

        return {"run_id": run_id, "succes": succes,
                "stdout": resultat.stdout, "stderr": resultat.stderr,
                "code_retour": resultat.returncode}

    except subprocess.TimeoutExpired:
        log("error", "timeout_expire", run_id=run_id, outil=outil, commande=commande)
        subprocess.run(["docker", "stop", container_name], capture_output=True, timeout=10)
        subprocess.run(["docker", "rm", "--force", container_name], capture_output=True, timeout=10)
        return {"run_id": run_id, "succes": False, "stdout": "",
                "stderr": f"Timeout ({TIMEOUT_SECONDS}s) — container arrêté.", "code_retour": -2}

    except FileNotFoundError:
        log("error", "docker_introuvable", run_id=run_id)
        return {"run_id": run_id, "succes": False, "stdout": "",
                "stderr": "Docker non trouvé.", "code_retour": -3}


# ── Tests ─────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "="*60)
    print("Agent IA : lancement des tests sandbox v3")
    print(f"OS détecté : {platform.system()} — pids-limit : {'actif' if IS_LINUX else 'désactivé (Windows)'}")
    print("="*60 + "\n")

    tests = [
        ("python",   "pytest",          "pytest"),
        ("python",   "lint",            "flake8 lint"),
        ("python",   "bandit",          "scan bandit"),
        ("python",   "pip-audit",       "pip-audit dépendances Python"),
        ("node",     "eslint",          "eslint Node.js"),
        ("security", "semgrep",         "scan SAST semgrep"),
        ("security", "detect-secrets",  "scan secrets"),
        ("security", "checkov",         "scan IaC checkov"),
        ("python",   "rm",              "rm — doit être refusée"),
    ]

    for outil, cmd, label in tests:
        print(f"▶ {label}")
        res = executer_dans_sandbox(outil, cmd)  # type: ignore
        if res["code_retour"] == -1:
            print(f"  [REFUS] run_id={res['run_id']} — OK\n")
        elif res["succes"]:
            print(f"  [OK]    run_id={res['run_id']}\n")
        else:
            print(f"  [ECHEC] run_id={res['run_id']} | code={res['code_retour']}")
            if res["stderr"]:
                for line in res["stderr"].strip().splitlines()[:4]:
                    print(f"          {line}")
            print()

    print("Logs : ./logs/sandbox.log")