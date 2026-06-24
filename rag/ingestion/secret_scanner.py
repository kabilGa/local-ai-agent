from __future__ import annotations

import hashlib
import json
import logging
import re
import subprocess
from typing import Tuple

logger = logging.getLogger(__name__)

REDACTION_PLACEHOLDER = "[REDACTED:SECRET]"

# Ordered: most specific first to avoid partial overlaps
_RAW_PATTERNS: list[str] = [
    # Private keys
    r"-----BEGIN\s+(?:RSA|EC|DSA|OPENSSH|PGP)\s+PRIVATE KEY(?:\s+BLOCK)?-----",
    # AWS
    r"(?i)AKIA[0-9A-Z]{16}",
    r"(?i)aws[_-]?(?:access[_-]?key[_-]?id|secret[_-]?access[_-]?key)\s*[:=]\s*['\"]?([A-Za-z0-9/+]{20,})",
    # GitHub / GitLab / generic tokens
    r"ghp_[A-Za-z0-9]{36}",
    r"ghs_[A-Za-z0-9]{36}",
    r"glpat-[A-Za-z0-9\-_]{10,}",
    r"xox[baprs]-[0-9A-Za-z\-]+",        # Slack
    r"sk-[A-Za-z0-9]{32,}",              # OpenAI-style
    # Generic API keys / tokens
    r"(?i)(?:api[_-]?key|apikey|x-api-key)\s*[:=]\s*['\"]?([A-Za-z0-9_\-]{20,})['\"]?",
    r"(?i)bearer\s+([A-Za-z0-9_\-\.]{20,})",
    r"(?i)(?:access[_-]?token|refresh[_-]?token|auth[_-]?token)\s*[:=]\s*['\"]([A-Za-z0-9_\-\.]{20,})['\"]",
    # Passwords in code
    r"(?i)(?:password|passwd|pwd|secret|passphrase)\s*[:=]\s*['\"]([^'\"]{8,})['\"]",
    # Connection strings
    r"(?i)(?:mongodb|postgres|postgresql|mysql|redis)://[^:]+:[^@]+@",
    # JWT
    r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
]

_COMPILED: list[re.Pattern] = [re.compile(p) for p in _RAW_PATTERNS]


class SecretScanner:
    """
    Two-pass scanner: compiled regex patterns + optional Gitleaks binary.

    CDC requirement: 100% detection on the synthetic secrets test corpus.
    Both passes must run in production (secret_scanner_enabled=True).
    """

    def __init__(self, gitleaks_binary: str = "gitleaks", enabled: bool = True):
        self.enabled = enabled
        self.gitleaks_binary = gitleaks_binary
        self._gitleaks_ok = self._probe_gitleaks()

    # ── Public API ────────────────────────────────────────────────────────────

    def scan_and_redact(self, content: str, file_path: str = "") -> Tuple[str, bool]:
        """
        Return (redacted_content, has_secrets).
        All detected secrets are replaced with REDACTION_PLACEHOLDER.
        This MUST be called before any chunking or indexing.
        """
        if not self.enabled:
            return content, False

        has_secrets = False
        redacted = content

        # Pass 1 — regex
        for pattern in _COMPILED:
            for match in pattern.finditer(redacted):
                has_secrets = True
                full_match = match.group(0)
                redacted = redacted.replace(full_match, REDACTION_PLACEHOLDER)
                logger.info("Secret redacted in '%s' (regex pattern)", file_path or "<stdin>")

        # Pass 2 — Gitleaks
        if self._gitleaks_ok:
            findings = self._run_gitleaks(redacted)
            for finding in findings:
                secret_val = finding.get("Secret", "")
                if secret_val and len(secret_val) >= 6 and secret_val in redacted:
                    has_secrets = True
                    redacted = redacted.replace(secret_val, REDACTION_PLACEHOLDER)
                    logger.info("Secret redacted in '%s' (gitleaks: %s)", file_path, finding.get("RuleID", "?"))

        return redacted, has_secrets

    def scan_only(self, content: str) -> bool:
        """Return True if any secret is detected (no redaction)."""
        _, has_secrets = self.scan_and_redact(content)
        return has_secrets

    @staticmethod
    def content_hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    # ── Internals ─────────────────────────────────────────────────────────────

    def _probe_gitleaks(self) -> bool:
        try:
            r = subprocess.run(
                [self.gitleaks_binary, "version"],
                capture_output=True,
                timeout=5,
            )
            available = r.returncode == 0
            if not available:
                logger.warning("gitleaks binary not functional — regex-only mode active")
            return available
        except (FileNotFoundError, subprocess.TimeoutExpired):
            logger.warning(
                "gitleaks not found at '%s' — regex-only mode active. "
                "Install from https://github.com/gitleaks/gitleaks/releases",
                self.gitleaks_binary,
            )
            return False

    def _run_gitleaks(self, content: str) -> list[dict]:
        try:
            proc = subprocess.run(
                [
                    self.gitleaks_binary, "detect",
                    "--source", "-",
                    "--report-format", "json",
                    "--no-git",
                    "--log-level", "warn",
                ],
                input=content.encode("utf-8", errors="replace"),
                capture_output=True,
                timeout=20,
            )
            # gitleaks exits 1 when leaks are found AND outputs JSON
            if proc.stdout:
                return json.loads(proc.stdout)
        except subprocess.TimeoutExpired:
            logger.warning("gitleaks timed out")
        except json.JSONDecodeError:
            pass
        except Exception as exc:
            logger.debug("gitleaks error: %s", exc)
        return []
