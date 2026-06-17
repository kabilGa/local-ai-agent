"""
Router Engine
=============
The core that ties everything together:
  1. Takes a user prompt
  2. Runs it through the classifier (which tier? which model?)
  3. Calls the chosen model via Ollama
  4. Returns the real answer + metadata (model used, timing, tier)

This is what makes the router a working assistant instead of just a classifier.

Usage:
    from router.engine import ask
    result = ask("What does len() do in Python?")
    print(result["answer"])
    print(result["model_used"], result["tier"], result["latency_s"])
"""

import time
import httpx
from router.classifier import classify_to_dict

OLLAMA_URL = "http://localhost:11434/api/generate"

# Response length cap per tier — simple questions get short answers, fast.
TIER_MAX_TOKENS = {
    "FAST":     1024,
    "BALANCED": 2048,
    "HEAVY":    4096,
}


def ask(prompt: str, stream: bool = False) -> dict:
    """
    The full router flow: classify -> call model -> return answer.

    Returns a dict:
        {
          "answer":      the model's text response,
          "model_used":  which model answered,
          "tier":        FAST / BALANCED / HEAVY,
          "reasoning":   why the router chose that tier,
          "confidence":  high / medium / low,
          "latency_s":   total time in seconds,
          "tokens_per_s": generation speed,
          "is_security": whether it was flagged as a security prompt,
        }
    """
    # ── 1. Classify the prompt ────────────────────────────────────────────────
    decision = classify_to_dict(prompt)
    tier     = decision["tier"]
    model    = decision["model"]
    max_tok  = TIER_MAX_TOKENS.get(tier, 512)

    # ── 2. Call the chosen model via Ollama ──────────────────────────────────
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": "30m",
        "options": {
            "temperature": 0.2,
            "num_predict": max_tok,
        },
    }

    start = time.time()
    try:
        resp = httpx.post(OLLAMA_URL, json=payload, timeout=300)
        latency = round(time.time() - start, 2)

        if resp.status_code != 200:
            return _error_result(decision, f"Ollama returned HTTP {resp.status_code}", latency)

        data = resp.json()
        answer = data.get("response", "").strip()

        # Calculate tokens/second from Ollama metadata
        tok_per_s = 0.0
        if data.get("eval_count") and data.get("eval_duration"):
            tok_per_s = round(data["eval_count"] / (data["eval_duration"] / 1e9), 1)

        # ── 3. Return the complete result ────────────────────────────────────
        return {
            "answer":       answer,
            "model_used":   model,
            "tier":         tier,
            "reasoning":    decision["reasoning"],
            "confidence":   decision["confidence"],
            "latency_s":    latency,
            "tokens_per_s": tok_per_s,
            "is_security":  decision["is_security_prompt"],
            "success":      True,
        }

    except httpx.TimeoutException:
        return _error_result(decision, "Model timed out (>300s)", round(time.time() - start, 2))
    except httpx.ConnectError:
        return _error_result(decision, "Cannot reach Ollama. Is it running? (ollama serve)", 0)
    except Exception as e:
        return _error_result(decision, f"Unexpected error: {e}", round(time.time() - start, 2))


def _error_result(decision: dict, error_msg: str, latency: float) -> dict:
    """Build a result dict for the error case, keeping the routing info."""
    return {
        "answer":       f"[ERROR] {error_msg}",
        "model_used":   decision["model"],
        "tier":         decision["tier"],
        "reasoning":    decision["reasoning"],
        "confidence":   decision["confidence"],
        "latency_s":    latency,
        "tokens_per_s": 0.0,
        "is_security":  decision["is_security_prompt"],
        "success":      False,
        "error":        error_msg,
    }


# ── Quick test when run directly ──────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  Router Engine — Live Test")
    print("=" * 60)

    test_prompts = [
        "What does len() do in Python?",
        "Write a function that checks if a number is prime.",
    ]

    for p in test_prompts:
        print(f"\nPrompt: {p}")
        print("-" * 60)
        result = ask(p)
        print(f"Tier:   {result['tier']}  ({result['confidence']} confidence)")
        print(f"Model:  {result['model_used']}")
        print(f"Time:   {result['latency_s']}s  |  {result['tokens_per_s']} tok/s")
        print(f"\nAnswer:\n{result['answer']}")
        print("=" * 60)
