"""Evaluation harness — compare baseline vector RAG vs hybrid graph retrieval.

Usage::

    from ragmen.eval import run_evaluation
    report = run_evaluation("firecraft", store, golden_set, no_judge=True)
    print(report.markdown())
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ragmen.eval.baseline import BaselineVectorRetriever
from ragmen.eval.metrics import EvalQuestionResult, EvalReport, SystemResult, compute_metrics
from ragmen.serve.retrievers import HybridRetriever


GOLDEN_DIR = Path(__file__).parents[3] / "eval" / "golden"
RESULTS_DIR = Path(__file__).parents[3] / "eval" / "results"
THRESHOLDS_PATH = Path(__file__).parents[3] / "eval" / "thresholds.yaml"
JUDGE_PROMPT_PATH = Path(__file__).parents[3] / "eval" / "judge_prompt.md"


def _load_golden_set(profile: str) -> list[dict]:
    path = GOLDEN_DIR / f"{profile}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"golden set not found: {path}")
    questions = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                questions.append(json.loads(line))
    return questions


def _load_thresholds(profile: str) -> dict[str, float]:
    if not THRESHOLDS_PATH.exists():
        return {}
    try:
        import yaml
        data = yaml.safe_load(THRESHOLDS_PATH.read_text(encoding="utf-8")) or {}
        return data.get(profile, {})
    except Exception:
        return {}


def _query_embedding(query: str) -> list[float]:
    """Deterministic mock embedding — must match serve/retrievers.py."""
    seed = hashlib.sha256(query.encode("utf-8")).digest()
    return [(0.1 if (seed[i % 32] + (i // 32)) % 2 == 0 else -0.1) for i in range(384)]


def run_evaluation(
    profile: str,
    store: Any,
    no_judge: bool = False,
    golden_path: str | Path | None = None,
) -> EvalReport:
    """Run full evaluation: baseline vs hybrid on a golden set.

    Args:
        profile: Profile name (for file paths).
        store: Populated MemoryStore or GraphStore.
        no_judge: Skip LLM judge (retrieval metrics only).
        golden_path: Override path to golden set JSONL.

    Returns:
        EvalReport with per-question and aggregate results.
    """
    golden_path = golden_path or GOLDEN_DIR / f"{profile}.jsonl"
    questions = _load_golden_set(profile) if golden_path == GOLDEN_DIR / f"{profile}.jsonl" else _load_question_set(golden_path)

    baseline = BaselineVectorRetriever(store)
    hybrid = HybridRetriever(store)

    per_type: dict[str, list[EvalQuestionResult]] = {}
    q_results: list[EvalQuestionResult] = []

    for q in questions:
        qid = q.get("id", q.get("question", "")[:20])
        qtype = q.get("type", "single_hop")
        question = q["question"]
        evidence = q.get("evidence_chunk_ids", [])

        qr = EvalQuestionResult(id=qid, question=question, type=qtype, evidence_chunk_ids=evidence)

        # Baseline
        t0 = time.perf_counter()
        q_emb = _query_embedding(question)
        baseline_ids = baseline.retrieve_chunk_ids(q_emb, top_k=10)
        t1 = time.perf_counter()
        qr.systems["baseline_vector"] = compute_metrics(baseline_ids, evidence, (t1 - t0) * 1000)

        # Hybrid
        t0 = time.perf_counter()
        hybrid_result = hybrid.retrieve(question, top_k=10, hops=1)
        hybrid_ids = [h.chunk_id for h in hybrid_result.hits]
        t1 = time.perf_counter()
        qr.systems["ragmen_hybrid"] = compute_metrics(hybrid_ids, evidence, (t1 - t0) * 1000)

        per_type.setdefault(qtype, []).append(qr)
        q_results.append(qr)

    total = len(q_results)
    date_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    thresholds = _load_thresholds(profile)

    report = EvalReport(
        profile=profile,
        date=date_str,
        total_questions=total,
        per_type=per_type,
        systems_compared=["baseline_vector", "ragmen_hybrid"],
        thresholds=thresholds,
    )
    return report


def _load_question_set(path: str | Path) -> list[dict]:
    questions = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                questions.append(json.loads(line))
    return questions


def save_report(report: EvalReport) -> tuple[Path, Path]:
    """Save report as markdown and raw JSON."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    md_path = RESULTS_DIR / f"{report.profile}_{report.date}.md"
    json_path = RESULTS_DIR / f"{report.profile}_{report.date}.json"

    md_path.write_text(report.markdown(), encoding="utf-8")

    raw = {
        "profile": report.profile,
        "date": report.date,
        "total_questions": report.total_questions,
        "systems": report.systems_compared,
        "per_type": {},
    }
    for qtype, results in report.per_type.items():
        raw["per_type"][qtype] = []
        for qr in results:
            raw["per_type"][qtype].append({
                "id": qr.id,
                "type": qr.type,
                "question": qr.question,
                "evidence": qr.evidence_chunk_ids,
                "systems": {
                    name: {
                        "recall@5": sr.recall_at_5,
                        "recall@10": sr.recall_at_10,
                        "mrr": sr.mrr,
                        "latency_ms": sr.latency_ms,
                        "citation_validity": sr.citation_validity,
                    }
                    for name, sr in qr.systems.items()
                },
            })
    json_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    return md_path, json_path


__all__ = ["run_evaluation", "save_report", "EvalReport"]