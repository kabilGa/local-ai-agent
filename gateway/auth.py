"""
Gateway Authentication and Quotas
=================================
Simple, honest implementations of two cahier des charges requirements:

  1. Authentication  - the gateway checks an API key before serving a request.
  2. Quotas          - the gateway limits how many requests a user can make
                       in a time window, so one user cannot flood the system.

This is a POC-level implementation:
  - API keys are read from a local file / environment, never hard-coded.
  - The quota counter lives in memory (resets on restart), which is fine for
    a prototype. A production version would use a database or Redis.

Both are deliberately simple but real: they demonstrate the security controls
the spec asks for without pretending to be enterprise infrastructure.
"""

import os
import time
from collections import defaultdict, deque

# ── Authentication ────────────────────────────────────────────────────────────
# Valid API keys. In a real deployment these come from a secrets store or an
# identity provider. For the POC we read a comma-separated list from an
# environment variable, with a sensible default so local dev still works.
#
#   set GATEWAY_API_KEYS=dev-key-123,teammate-key-456   (PowerShell: $env:...)
#
# If no keys are configured, auth runs in "open" mode (useful for local dev),
# and the gateway logs a warning so this is never a silent security hole.

_raw_keys = os.environ.get("GATEWAY_API_KEYS", "").strip()
VALID_KEYS = set(k.strip() for k in _raw_keys.split(",") if k.strip())
AUTH_ENABLED = len(VALID_KEYS) > 0


def check_api_key(api_key: str | None) -> bool:
    """Return True if the request is allowed to proceed."""
    if not AUTH_ENABLED:
        return True            # open mode for local dev (a warning is logged at startup)
    return api_key in VALID_KEYS


def auth_status() -> dict:
    """Describe the current auth configuration (without leaking the keys)."""
    return {"auth_enabled": AUTH_ENABLED, "configured_keys": len(VALID_KEYS)}


# ── Quotas / rate limiting ────────────────────────────────────────────────────
# Sliding-window limiter: each identity (API key or user) may make at most
# MAX_REQUESTS requests per WINDOW_SECONDS. Older timestamps fall out of the
# window automatically.

MAX_REQUESTS = int(os.environ.get("GATEWAY_RATE_LIMIT", "30"))
WINDOW_SECONDS = int(os.environ.get("GATEWAY_RATE_WINDOW", "60"))

# identity -> deque of request timestamps
_hits: dict[str, deque] = defaultdict(deque)


def check_quota(identity: str) -> tuple[bool, int]:
    """
    Record a request for this identity and check whether it's within quota.
    Returns (allowed, remaining).
    """
    now = time.time()
    window_start = now - WINDOW_SECONDS
    q = _hits[identity]

    # Drop timestamps older than the window
    while q and q[0] < window_start:
        q.popleft()

    if len(q) >= MAX_REQUESTS:
        return False, 0

    q.append(now)
    remaining = MAX_REQUESTS - len(q)
    return True, remaining


def quota_status() -> dict:
    return {"max_requests": MAX_REQUESTS, "window_seconds": WINDOW_SECONDS}
