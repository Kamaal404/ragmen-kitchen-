"""Evaluation metrics for retrieval systems."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvalQuestionResult:
    id: str
    question: str
    type: str  # single_hop | multi_hop | global
    evidence_chunk_ids: list[str]

    # Per-system results
    systems: dict[str, SystemResult] = field(default_factory=dict)

    # Judge verdict (LLM or None)
    judge_score: int | None = None
    judge_reason: str = ""


@dataclass
class SystemResult:
    retrieved_chunk_ids: list[str] = field(default_factory=list)
    recall_at_5: float = 0.0
    recall_at_10: float = 0.0
    mrr: float = 0.0
    latency_ms: float = 0.0
    citation_validity: float = 0.0  # % of cited chunks that are in evidence set


def _recall(retrieved: list[str], relevant: set[str], k: int) -> float:
    top_k = set(retrieved[:k])
    if not relevant:
        return 0.0
    return len(top_k & relevant) / len(relevant)


def _mrr(retrieved: list[str], relevant: set[str]) -> float:
    for i, cid in enumerate(retrieved):
        if cid in relevant:
            return 1.0 / (i + 1)
    return 0.0


def compute_metrics(
    retrieved_ids: list[str],
    evidence_chunk_ids: list[str],
    latency_ms: float,
) -> SystemResult:
    relevant = set(evidence_chunk_ids)
    valid_count = sum(1 for cid in retrieved_ids[:10] if cid in relevant)
    return SystemResult(
        retrieved_chunk_ids=list(retrieved_ids),
        recall_at_5=_recall(retrieved_ids, relevant, 5),
        recall_at_10=_recall(retrieved_ids, relevant, 10),
        mrr=_mrr(retrieved_ids, relevant),
        latency_ms=round(latency_ms, 1),
        citation_validity=valid_count / max(1, len(retrieved_ids[:10])),
    )


@dataclass
class EvalReport:
    profile: str
    date: str
    total_questions: int
    per_type: dict[str, list[EvalQuestionResult]]
    systems_compared: list[str]
    thresholds: dict[str, float] = field(default_factory=dict)

    def aggregate(self, system: str) -> dict[str, Any]:
        """Aggregate metrics across all questions for one system."""
        agg: dict[str, list[float]] = {
            "recall_at_5": [],
            "recall_at_10": [],
            "mrr": [],
            "latency_ms": [],
            "citation_validity": [],
        }
        for results in self.per_type.values():
            for qr in results:
                sr = qr.systems.get(system)
                if sr is None:
                    continue
                agg["recall_at_5"].append(sr.recall_at_5)
                agg["recall_at_10"].append(sr.recall_at_10)
                agg["mrr"].append(sr.mrr)
                agg["latency_ms"].append(sr.latency_ms)
                agg["citation_validity"].append(sr.citation_validity)

        def _avg(vals: list[float]) -> float:
            return round(sum(vals) / max(1, len(vals)), 4)

        return {
            "system": system,
            "questions": len(agg["recall_at_5"]),
            "avg_recall@5": _avg(agg["recall_at_5"]),
            "avg_recall@10": _avg(agg["recall_at_10"]),
            "avg_mrr": _avg(agg["mrr"]),
            "avg_latency_ms": _avg(agg["latency_ms"]),
            "avg_citation_validity": _avg(agg["citation_validity"]),
        }

    def markdown(self) -> str:
        lines = [
            f"# Evaluation: {self.profile}",
            f"Date: {self.date}",
            f"Questions: {self.total_questions}",
            f"Systems: {', '.join(self.systems_compared)}",
            "",
            "## Overall",
        ]
        # Build table
        headers = ["System", "Questions", "Recall@5", "Recall@10", "MRR", "Latency (ms)", "Citation Validity"]
        rows = []
        for sys_name in self.systems_compared:
            a = self.aggregate(sys_name)
            rows.append([
                sys_name,
                str(a["questions"]),
                f"{a['avg_recall@5']:.2%}",
                f"{a['avg_recall@10']:.2%}",
                f"{a['avg_mrr']:.3f}",
                f"{a['avg_latency_ms']:.0f}",
                f"{a['avg_citation_validity']:.1%}",
            ])
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "|".join("---" for _ in headers) + "|")
        for row in rows:
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")

        # Per-type breakdown
        for qtype, results in sorted(self.per_type.items()):
            lines.append(f"## {qtype} ({len(results)} questions)")
            lines.append("")
            type_rows: dict[str, list[float]] = {}
            for sys_name in self.systems_compared:
                type_rows[sys_name] = []
                for qr in results:
                    sr = qr.systems.get(sys_name)
                    if sr:
                        type_rows[sys_name].extend([sr.recall_at_5, sr.recall_at_10, sr.mrr])

            headers_t = ["System", "Questions", "Recall@5", "Recall@10", "MRR"]
            type_table = []
            for sys_name in self.systems_compared:
                vals = type_rows.get(sys_name, [])
                if not vals:
                    continue
                n = len(results)
                r5 = round(sum(vals[::3]) / max(1, n), 4)
                r10 = round(sum(vals[1::3]) / max(1, n), 4)
                mrr = round(sum(vals[2::3]) / max(1, n), 4)
                type_table.append([sys_name, str(n), f"{r5:.2%}", f"{r10:.2%}", f"{mrr:.3f}"])
            lines.append("| " + " | ".join(headers_t) + " |")
            lines.append("|" + "|".join("---" for _ in headers_t) + "|")
            for row in type_table:
                lines.append("| " + " | ".join(row) + " |")
            lines.append("")

        # Thresholds
        if self.thresholds:
            lines.append("## Thresholds")
            for k, v in self.thresholds.items():
                actual = None
                for sys_name in self.systems_compared:
                    a = self.aggregate(sys_name)
                    if k.startswith(sys_name):
                        metric = k.replace(sys_name + "_", "")
                        actual = a.get(metric, a.get(f"avg_{metric}", None))
                status = "PASS" if actual is not None and actual >= v else "FAIL"
                lines.append(f"  {k}: required={v} actual={actual} [{status}]")
            lines.append("")

        return "\n".join(lines)


__all__ = ["EvalQuestionResult", "SystemResult", "EvalReport", "compute_metrics"]