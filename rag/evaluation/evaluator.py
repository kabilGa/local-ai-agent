from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TestCase:
    query: str
    expected_chunk_ids: List[str]
    expected_file_paths: List[str] = field(default_factory=list)
    category: str = "general"          # debugging | security | refactoring | general
    project_id: str = ""
    notes: str = ""


@dataclass
class EvalResult:
    recall_at_5: float
    mrr: float
    precision_at_5: float
    passes: bool
    total_cases: int
    target_recall: float = 0.95
    per_category: Dict[str, float] = field(default_factory=dict)
    failed_cases: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recall_at_5": round(self.recall_at_5, 4),
            "mrr": round(self.mrr, 4),
            "precision_at_5": round(self.precision_at_5, 4),
            "passes": self.passes,
            "total_cases": self.total_cases,
            "target_recall": self.target_recall,
            "per_category": {k: round(v, 4) for k, v in self.per_category.items()},
            "failed_cases_count": len(self.failed_cases),
        }


class RAGEvaluator:
    """
    Offline evaluation framework for the RAG engine.

    Metrics:
    - Recall@5  : ≥ 95% target (CDC §12)
    - MRR       : Mean Reciprocal Rank
    - Precision@5

    Usage:
        evaluator = RAGEvaluator()
        dataset = evaluator.load_dataset("eval_dataset.json")
        result = await evaluator.evaluate(dataset, rag_engine)
        print(result.to_dict())
    """

    def __init__(self, target_recall: float = 0.95, top_k: int = 5):
        self.target_recall = target_recall
        self.top_k = top_k

    # ── Evaluation ────────────────────────────────────────────────────────────

    async def evaluate(
        self,
        dataset: List[TestCase],
        rag_engine,           # HybridSearcher instance
        project_id: str = "",
        allowed_roles: Optional[List[str]] = None,
    ) -> EvalResult:
        """Run all test cases and return aggregated metrics."""
        roles = allowed_roles or ["developer"]
        recall_scores: List[float] = []
        mrr_scores: List[float] = []
        precision_scores: List[float] = []
        by_category: Dict[str, List[float]] = {}
        failed: List[Dict] = []

        for case in dataset:
            pid = case.project_id or project_id
            results = await rag_engine.search(
                query=case.query,
                project_id=pid,
                allowed_roles=roles,
                top_k=self.top_k,
            )

            retrieved_ids = self._extract_ids(results)
            expected = set(case.expected_chunk_ids)

            # Recall@K
            hits = len(expected & set(retrieved_ids[:self.top_k]))
            recall = hits / len(expected) if expected else 0.0
            recall_scores.append(recall)

            # Precision@K
            precision = hits / min(self.top_k, len(retrieved_ids)) if retrieved_ids else 0.0
            precision_scores.append(precision)

            # MRR
            mrr = 0.0
            for rank, rid in enumerate(retrieved_ids[:self.top_k], 1):
                if rid in expected:
                    mrr = 1.0 / rank
                    break
            mrr_scores.append(mrr)

            # Per-category
            by_category.setdefault(case.category, []).append(recall)

            if recall < self.target_recall:
                failed.append({
                    "query": case.query,
                    "category": case.category,
                    "recall": round(recall, 3),
                    "expected_ids": list(expected),
                    "retrieved_ids": retrieved_ids[:self.top_k],
                })

        n = len(dataset)
        final_recall = sum(recall_scores) / n if n else 0.0
        final_mrr = sum(mrr_scores) / n if n else 0.0
        final_precision = sum(precision_scores) / n if n else 0.0

        logger.info(
            "[eval] Recall@%d=%.3f  MRR=%.3f  Precision@%d=%.3f  (n=%d, target=%.2f)",
            self.top_k, final_recall, final_mrr, self.top_k, final_precision, n, self.target_recall,
        )

        return EvalResult(
            recall_at_5=final_recall,
            mrr=final_mrr,
            precision_at_5=final_precision,
            passes=final_recall >= self.target_recall,
            total_cases=n,
            target_recall=self.target_recall,
            per_category={k: sum(v) / len(v) for k, v in by_category.items()},
            failed_cases=failed[:20],   # Cap for readability
        )

    # ── Synthetic dataset generation ──────────────────────────────────────────

    @staticmethod
    def generate_test_cases(
        chunks,                   # List[CodeChunk]
        sample_size: int = 100,
        seed: int = 42,
    ) -> List[TestCase]:
        """
        Generate a synthetic evaluation dataset from indexed chunks.

        For each function chunk, create a natural-language query that a developer
        would use to find it. The expected answer is that chunk's ID.

        Uses simple heuristic templates — replace with LLM generation for
        higher quality (see generate_hyde in QueryPreprocessor).
        """
        random.seed(seed)
        function_chunks = [c for c in chunks if c.node_type in ("function", "method")]
        selected = random.sample(function_chunks, min(sample_size, len(function_chunks)))

        cases = []
        for chunk in selected:
            query = _heuristic_query(chunk)
            if query:
                cases.append(TestCase(
                    query=query,
                    expected_chunk_ids=[chunk.chunk_id],
                    expected_file_paths=[chunk.file_path],
                    category=_classify_chunk(chunk),
                    project_id=chunk.project_id,
                ))

        logger.info("[eval] Generated %d synthetic test cases", len(cases))
        return cases

    # ── Dataset I/O ───────────────────────────────────────────────────────────

    @staticmethod
    def save_dataset(cases: List[TestCase], path: str) -> None:
        with open(path, "w") as f:
            json.dump([c.__dict__ for c in cases], f, indent=2)
        logger.info("[eval] Saved %d test cases to %s", len(cases), path)

    @staticmethod
    def load_dataset(path: str) -> List[TestCase]:
        with open(path) as f:
            raw = json.load(f)
        cases = [TestCase(**r) for r in raw]
        logger.info("[eval] Loaded %d test cases from %s", len(cases), path)
        return cases

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_ids(results: List[Dict[str, Any]]) -> List[str]:
        ids = []
        for r in results:
            # RRF-fused result
            rid = r.get("id", "")
            if not rid:
                payload = r.get("payload", {})
                rid = payload.get("chunk_id", "")
            if rid:
                ids.append(str(rid))
        return ids


# ── Heuristic query templates ─────────────────────────────────────────────────

def _heuristic_query(chunk) -> Optional[str]:
    """Build a simple natural-language query from chunk metadata."""
    name = chunk.node_name
    if not name or name in ("anonymous", "unknown"):
        return None

    lang = chunk.language
    parent = chunk.parent_class

    if parent:
        return f"How does {parent}.{name} work in {lang}?"
    if chunk.docstring:
        # Use the first sentence of the docstring
        first_sentence = chunk.docstring.split(".")[0].strip("\"' ")
        if len(first_sentence) > 10:
            return first_sentence + "?"
    if chunk.calls:
        callee = chunk.calls[0]
        return f"Where is {callee} called in {lang}?"
    return f"What does the {name} function do?"


def _classify_chunk(chunk) -> str:
    name_lower = chunk.node_name.lower()
    content_lower = chunk.content.lower()
    if any(k in name_lower for k in ("auth", "login", "password", "token", "encrypt")):
        return "security"
    if any(k in name_lower for k in ("test", "spec", "assert", "mock")):
        return "testing"
    if any(k in content_lower for k in ("exception", "error", "raise", "panic", "throw")):
        return "debugging"
    return "general"
