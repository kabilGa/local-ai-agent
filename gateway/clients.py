"""
Gateway Service Clients
=======================
A thin layer between the gateway and each backend service.

WHY THIS EXISTS:
The gateway should not care HOW a service is reached. Today each client
just imports and calls the service function directly (simple, one process).
Later, if the team moves to true microservices, we change ONLY the insides
of these functions to make an HTTP call instead - the gateway code that
calls them never changes.

Each client returns a ServiceResult so the gateway gets a consistent shape
back no matter which service was called, and no matter how it was reached.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.models import ServiceResult


# ── ROUTER ────────────────────────────────────────────────────────────────────
def call_router(prompt: str) -> ServiceResult:
    """
    Ask the router which model should answer, then get the answer.
    The router team's code lives in router/. We import its engine.
    """
    try:
        from router.engine import ask
        result = ask(prompt)
        return ServiceResult(service="router", data=result, success=result.get("success", True))
    except ImportError:
        return ServiceResult(
            service="router", data=None, success=False,
            error="Router service not available (router/engine.py not found)"
        )
    except Exception as e:
        return ServiceResult(service="router", data=None, success=False, error=str(e))


# ── RAG (stub - teammate fills this in) ───────────────────────────────────────
def rag_available() -> bool:
    """Honest check: is the RAG service actually built? Used by /services/status."""
    try:
        from rag.engine import search  # type: ignore
        return callable(search)
    except Exception:
        return False


def call_rag(prompt: str, repo_name: str | None = None) -> ServiceResult:
    """
    Retrieve relevant code chunks for the prompt.
    If RAG isn't built yet, returns success=True with empty chunks so the
    /agent flow keeps working (just without code context). For an honest
    "is it built" answer, use rag_available() instead.
    """
    try:
        # When ready, the RAG team exposes: from rag.engine import search
        from rag.engine import search          # type: ignore
        chunks = search(prompt, repo_name)
        return ServiceResult(service="rag", data={"chunks": chunks}, success=True)
    except ImportError:
        # Graceful: RAG not built yet. Gateway still works without context.
        return ServiceResult(
            service="rag", data={"chunks": []}, success=True,
            error="RAG not available yet - proceeding without code context"
        )
    except Exception as e:
        return ServiceResult(service="rag", data={"chunks": []}, success=False, error=str(e))


# ── SANDBOX ───────────────────────────────────────────────────────────────────
def call_sandbox(tool: str, command: str, workspace_path: str = "./workspace") -> ServiceResult:
    """
    Run an allow-listed command safely inside the teammate's Docker sandbox.

    The sandbox (sandbox/sandbox_runner.py) exposes executer_dans_sandbox(outil, commande),
    which runs the command in a locked-down Docker container. It REQUIRES Docker to be
    installed and running. On machines without Docker (like this gateway's dev machine),
    we catch that and return a clean 'Docker required' message instead of crashing.

    Args:
        tool:    one of "python", "node", "security"
        command: the command to run (must be on the sandbox's allowlist)
        workspace_path: folder mounted into the container (read-only)
    """
    try:
        from sandbox.sandbox_runner import executer_dans_sandbox  # type: ignore

        result = executer_dans_sandbox(tool, command, workspace_path)

        # Translate the sandbox's French keys into the gateway's standard shape
        normalized = {
            "run_id":      result.get("run_id"),
            "success":     result.get("succes", False),
            "stdout":      result.get("stdout", ""),
            "stderr":      result.get("stderr", ""),
            "return_code": result.get("code_retour"),
        }
        return ServiceResult(
            service="sandbox",
            data=normalized,
            success=normalized["success"],
            error=None if normalized["success"] else normalized["stderr"],
        )

    except ImportError:
        return ServiceResult(
            service="sandbox", data=None, success=False,
            error="Sandbox module not found (sandbox/sandbox_runner.py)"
        )
    except FileNotFoundError:
        # This is what happens when 'docker' isn't installed: subprocess can't find it.
        return ServiceResult(
            service="sandbox", data=None, success=False,
            error="Sandbox requires Docker, which is not installed on this machine. "
                  "The sandbox will run on any machine that has Docker."
        )
    except Exception as e:
        # Catch-all, including Docker-daemon-not-running errors
        msg = str(e)
        if "docker" in msg.lower():
            msg = "Sandbox requires Docker to be installed and running. " + msg
        return ServiceResult(service="sandbox", data=None, success=False, error=msg)


# ── SECURITY (stub) ───────────────────────────────────────────────────────────
def call_security(file_path: str) -> ServiceResult:
    """Run SAST scan. STUB until security/ is built."""
    try:
        from security.scanner import scan       # type: ignore
        findings = scan(file_path)
        return ServiceResult(service="security", data={"findings": findings}, success=True)
    except ImportError:
        return ServiceResult(
            service="security", data=None, success=False,
            error="Security service not available yet"
        )
    except Exception as e:
        return ServiceResult(service="security", data=None, success=False, error=str(e))
