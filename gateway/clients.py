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
def call_rag(prompt: str, repo_name: str | None = None) -> ServiceResult:
    """
    Retrieve relevant code chunks for the prompt.
    STUB: returns empty context until the RAG team wires up rag/.
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


# ── SANDBOX (stub) ────────────────────────────────────────────────────────────
def call_sandbox(code: str, timeout: int = 30) -> ServiceResult:
    """Run code safely in isolation. STUB until sandbox/ is built."""
    try:
        from sandbox.runner import run_code     # type: ignore
        output = run_code(code, timeout=timeout)
        return ServiceResult(service="sandbox", data=output, success=True)
    except ImportError:
        return ServiceResult(
            service="sandbox", data=None, success=False,
            error="Sandbox not available yet"
        )
    except Exception as e:
        return ServiceResult(service="sandbox", data=None, success=False, error=str(e))


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
