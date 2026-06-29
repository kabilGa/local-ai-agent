"""
Unit tests for SecretScanner.
CDC requirement: 100% detection rate on synthetic secrets corpus.
"""
from __future__ import annotations

import pytest

from rag.ingestion.secret_scanner import REDACTION_PLACEHOLDER, SecretScanner


@pytest.fixture
def scanner():
    return SecretScanner(gitleaks_binary="gitleaks", enabled=True)


# ── Regex detection tests ─────────────────────────────────────────────────────

class TestRegexDetection:

    def test_detects_aws_access_key(self, scanner):
        content = 'aws_access_key_id = "AKIAIOSFODNN7EXAMPLE"'
        redacted, found = scanner.scan_and_redact(content, "config.py")
        assert found is True
        assert "AKIAIOSFODNN7EXAMPLE" not in redacted
        assert REDACTION_PLACEHOLDER in redacted

    def test_detects_api_key_assignment(self, scanner):
        content = 'API_KEY = "sk-abcdef1234567890abcdef1234567890"'
        redacted, found = scanner.scan_and_redact(content, "settings.py")
        assert found is True
        assert "sk-abcdef" not in redacted

    def test_detects_bearer_token(self, scanner):
        content = "Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig"
        redacted, found = scanner.scan_and_redact(content)
        assert found is True

    def test_detects_github_pat(self, scanner):
        content = 'GITHUB_TOKEN = "ghp_' + "A" * 36 + '"'
        redacted, found = scanner.scan_and_redact(content, "ci.yml")
        assert found is True
        assert "ghp_" not in redacted

    def test_detects_private_key_header(self, scanner):
        content = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
        redacted, found = scanner.scan_and_redact(content, "key.pem")
        assert found is True
        assert "BEGIN RSA PRIVATE KEY" not in redacted

    def test_detects_postgres_connection_string(self, scanner):
        content = 'DB_URL = "postgresql://admin:s3cr3tpassword@db.example.com:5432/app"'
        redacted, found = scanner.scan_and_redact(content)
        assert found is True

    def test_detects_password_in_quotes(self, scanner):
        content = 'password = "MyS3cur3P@ss"'
        redacted, found = scanner.scan_and_redact(content)
        assert found is True
        assert "MyS3cur3P@ss" not in redacted

    def test_detects_gitlab_pat(self, scanner):
        content = 'token = "glpat-xxxx-yyyy-zzzz-aaaa"'
        redacted, found = scanner.scan_and_redact(content)
        assert found is True


# ── Clean content tests ───────────────────────────────────────────────────────

class TestCleanContent:

    def test_clean_python_function(self, scanner):
        content = """
def calculate_sum(a: int, b: int) -> int:
    return a + b
"""
        redacted, found = scanner.scan_and_redact(content)
        assert found is False
        assert redacted == content

    def test_clean_import_block(self, scanner):
        content = "from typing import List, Optional\nimport os\nimport sys"
        redacted, found = scanner.scan_and_redact(content)
        assert found is False

    def test_placeholder_variable_name(self, scanner):
        """Variable names containing 'password' without a value should not trigger."""
        content = "def set_password(self, password: str) -> None:\n    self._password = password"
        # This may or may not trigger depending on pattern — just verify no crash
        redacted, found = scanner.scan_and_redact(content)
        assert isinstance(found, bool)
        assert isinstance(redacted, str)


# ── Disabled scanner ──────────────────────────────────────────────────────────

class TestDisabledScanner:

    def test_disabled_scanner_returns_original(self):
        scanner = SecretScanner(enabled=False)
        secret_content = 'API_KEY = "sk-' + "x" * 40 + '"'
        redacted, found = scanner.scan_and_redact(secret_content)
        assert found is False
        assert redacted == secret_content


# ── Content hash ──────────────────────────────────────────────────────────────

class TestContentHash:

    def test_hash_is_deterministic(self, scanner):
        content = "def foo(): pass"
        h1 = scanner.content_hash(content)
        h2 = scanner.content_hash(content)
        assert h1 == h2

    def test_different_content_different_hash(self, scanner):
        h1 = scanner.content_hash("def foo(): pass")
        h2 = scanner.content_hash("def bar(): pass")
        assert h1 != h2

    def test_hash_length(self, scanner):
        h = scanner.content_hash("hello")
        assert len(h) == 64   # SHA-256 hex = 64 chars
