"""
LLM Router — Core Module
=========================
Classifies a prompt into FAST / BALANCED / HEAVY
and returns the best model to use based on benchmark results.

Usage:
    from router.classifier import classify_prompt
    result = classify_prompt("What does len() do?")
    # → {"tier": "FAST", "model": "phi3:mini", "reasoning": [...], "estimated_latency_s": 1}
"""

import re
from dataclasses import dataclass
from typing import Literal

# ── Tier type ─────────────────────────────────────────────────────────────────
Tier = Literal["FAST", "BALANCED", "HEAVY"]

# ── Model config (update this after running benchmark.py) ─────────────────────
# These defaults will be overwritten once you run the benchmark and see results.
# The benchmark generates the correct values at the bottom of report.md

MODEL_TIERS: dict[Tier, str] = {
    "FAST":     "qwen2.5-coder:1.5b",
    "BALANCED": "qwen2.5-coder:3b",
    "HEAVY":    "qwen2.5-coder:7b",
}

ESTIMATED_LATENCY: dict[Tier, float] = {
    "FAST":     1.5,
    "BALANCED": 3.5,
    "HEAVY":    7.0,
}

# ── Signal definitions ─────────────────────────────────────────────────────────

# Any of these → immediately HEAVY, no further checks
HEAVY_OVERRIDE_KEYWORDS = [
    "vulnerability", "vulnerabilities", "security audit", "owasp", "sql injection",
    "xss", "csrf", "ssrf", "cve", "exploit", "penetration", "pentest",
    "authentication bypass", "privilege escalation", "rce", "remote code execution",
    "injection", "hardened", "threat model", "attack surface",
]

# Strong signals for HEAVY
HEAVY_KEYWORDS = [
    "audit", "refactor", "architecture", "design pattern", "solid principle",
    "thread-safe", "concurrency", "race condition", "performance bottleneck",
    "microservice", "distributed", "scale", "optimize the entire",
    "complete implementation", "production-ready", "code review",
    "all vulnerabilities", "all issues", "all bugs",
]

# Strong signals for BALANCED
BALANCED_KEYWORDS = [
    "debug", "fix this", "fix the", "error", "exception", "stack trace",
    "traceback", "write a function", "write a class", "implement",
    "refactor this", "what's wrong", "why is", "how does", "explain this code",
    "decorator", "middleware", "async", "thread",
]

# Strong signals for FAST
FAST_KEYWORDS = [
    "what is", "what does", "what are", "define", "explain what",
    "rename", "convert", "translate to comment", "one-liner",
    "difference between", "when should i use", "simple question",
]

# Code-presence patterns — if any match, bump tier up by one
CODE_PATTERNS = [
    r"```",                        # markdown code block
    r"def [a-zA-Z_]+\(",          # Python function def
    r"class [A-Z][a-zA-Z]+",      # class definition
    r"Traceback \(most recent",    # Python stack trace
    r"File \".*\", line \d+",     # stack trace line
    r"[A-Z][a-zA-Z]+Error:",      # exception type
    r"SELECT .* FROM",             # SQL query
    r"FROM [a-zA-Z]+\n",          # Dockerfile FROM
    r"import [a-z]",              # Python import
]

# Multi-step intent — bump to HEAVY
MULTI_STEP_PATTERNS = [
    r"\band then\b", r"\balso\b.*\balso\b", r"\bstep by step\b",
    r"\band explain\b", r"\band provide\b", r"\band suggest\b",
    r"[.?!][^.?!]{0,50}[.?!][^.?!]{0,50}[.?!]",  # 3+ sentences in prompt
]


@dataclass
class RouterResult:
    tier: Tier
    model: str
    reasoning: list[str]
    estimated_latency_s: float
    confidence: Literal["high", "medium", "low"]
    prompt_length: int
    has_code: bool
    is_security: bool


def classify_prompt(prompt: str) -> RouterResult:
    """
    Classify a prompt into FAST / BALANCED / HEAVY.
    Returns a RouterResult with the selected model and full reasoning trace.
    """
    prompt_lower = prompt.lower().strip()
    reasoning    = []
    score        = 0  # 0 = FAST, 5 = BALANCED, 10 = HEAVY

    # ── 1. Security override (highest priority) ───────────────────────────────
    security_hits = [kw for kw in HEAVY_OVERRIDE_KEYWORDS if kw in prompt_lower]
    is_security   = len(security_hits) > 0
    if is_security:
        reasoning.append(f"🔴 SECURITY OVERRIDE: found keywords {security_hits} → forced to HEAVY")
        tier       = "HEAVY"
        confidence = "high"
        return RouterResult(
            tier=tier,
            model=MODEL_TIERS[tier],
            reasoning=reasoning,
            estimated_latency_s=ESTIMATED_LATENCY[tier],
            confidence=confidence,
            prompt_length=len(prompt.split()),
            has_code=bool(_has_code(prompt)),
            is_security=True,
        )

    # ── 2. Prompt length signal ───────────────────────────────────────────────
    word_count = len(prompt.split())
    if word_count < 12:
        score -= 2
        reasoning.append(f"✅ Short prompt ({word_count} words) → leans FAST")
    elif word_count < 40:
        reasoning.append(f"⚪ Medium prompt ({word_count} words) → neutral")
    else:
        score += 3
        reasoning.append(f"🟡 Long prompt ({word_count} words) → leans BALANCED/HEAVY")

    # ── 3. Code presence ─────────────────────────────────────────────────────
    has_code = _has_code(prompt)
    if has_code:
        score += 3
        reasoning.append("🟡 Code/stack trace detected → +1 tier bump")

    # ── 4. Heavy keyword check ────────────────────────────────────────────────
    heavy_hits = [kw for kw in HEAVY_KEYWORDS if kw in prompt_lower]
    if heavy_hits:
        score += 4
        reasoning.append(f"🟠 Heavy keywords found: {heavy_hits}")

    # ── 5. Balanced keyword check ─────────────────────────────────────────────
    balanced_hits = [kw for kw in BALANCED_KEYWORDS if kw in prompt_lower]
    if balanced_hits and not heavy_hits:
        score += 2
        reasoning.append(f"🟡 Balanced keywords found: {balanced_hits}")

    # ── 6. Fast keyword check ────────────────────────────────────────────────
    fast_hits = [kw for kw in FAST_KEYWORDS if kw in prompt_lower]
    if fast_hits and not balanced_hits and not heavy_hits:
        score -= 2
        reasoning.append(f"✅ Fast keywords found: {fast_hits}")

    # ── 7. Multi-step intent ─────────────────────────────────────────────────
    multi_step = any(re.search(p, prompt_lower) for p in MULTI_STEP_PATTERNS)
    if multi_step:
        score += 3
        reasoning.append("🟠 Multi-step intent detected → bumped toward HEAVY")

    # ── 8. Map score to tier ─────────────────────────────────────────────────
    if score <= 1:
        tier       = "FAST"
        confidence = "high" if score <= -1 else "medium"
    elif score <= 5:
        tier       = "BALANCED"
        confidence = "medium"
    else:
        tier       = "HEAVY"
        confidence = "high" if score >= 8 else "medium"

    reasoning.append(f"📊 Final score: {score} → {tier} (confidence: {confidence})")

    return RouterResult(
        tier=tier,
        model=MODEL_TIERS[tier],
        reasoning=reasoning,
        estimated_latency_s=ESTIMATED_LATENCY[tier],
        confidence=confidence,
        prompt_length=word_count,
        has_code=has_code,
        is_security=False,
    )


def _has_code(prompt: str) -> bool:
    return any(re.search(p, prompt) for p in CODE_PATTERNS)


def classify_to_dict(prompt: str) -> dict:
    """Convenience wrapper — returns a plain dict for API responses."""
    r = classify_prompt(prompt)
    return {
        "tier":               r.tier,
        "model":              r.model,
        "reasoning":          r.reasoning,
        "estimated_latency_s": r.estimated_latency_s,
        "confidence":         r.confidence,
        "prompt_length_words": r.prompt_length,
        "has_code":           r.has_code,
        "is_security_prompt": r.is_security,
    }


# ── Quick test when run directly ──────────────────────────────────────────────
if __name__ == "__main__":
    test_prompts = [
        "What does len() do in Python?",
        "Fix this bug: AttributeError: NoneType has no attribute split",
        "Audit my authentication module for SQL injection and OWASP vulnerabilities",
        "Write a decorator that measures execution time",
        "What is a variable?",
        "Refactor this entire payment processing system and explain the SOLID principles",
    ]

    print("\n" + "="*60)
    print("  Router Classifier — Quick Test")
    print("="*60)
    for p in test_prompts:
        result = classify_to_dict(p)
        print(f"\nPrompt : {p[:70]}...")
        print(f"  Tier  : {result['tier']}")
        print(f"  Model : {result['model']}")
        print(f"  Conf  : {result['confidence']}")
        for r in result['reasoning']:
            print(f"  {r}")