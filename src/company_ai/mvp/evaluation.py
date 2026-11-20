"""Score annotated, independently worded questions against the approved index."""

from collections import defaultdict
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any

from company_ai.data.normalization import normalize
from company_ai.mvp.db import company_transaction
from company_ai.mvp.knowledge import Embeddings, read_jsonl, search
from company_ai.mvp.policy import redact_contact


def evaluate(dsn: str, path: Path, embeddings: Embeddings | None = None) -> dict[str, Any]:
    metrics = defaultdict(list)
    for case in read_jsonl(path):
        company, language = case["company"], case["language"]
        expected, question = case["expected_id"], case["question"]
        kind = case.get("kind", "faq")
        product = normalize(case.get("product", "")).casefold()
        version = normalize(case.get("version", "")).casefold()
        if (language not in {"en", "km", "mixed"} or kind not in {"faq", "procedure"}
                or not isinstance(expected, str) or not 1 <= len(question) <= 900):
            raise ValueError("Invalid evaluation case.")
        with company_transaction(dsn, company) as conn:
            if expected and not conn.execute("""
                SELECT 1 FROM knowledge WHERE company_id=%s AND id=%s AND status='APPROVED'
                    AND kind=%s AND (product='' OR product=%s) AND (version='' OR version=%s)
            """, (company, expected, kind, product, version)).fetchone():
                raise ValueError("Expected answer is outside the approved evaluation scope.")
            modes = ("lexical", "hybrid") if embeddings else ("lexical",)
            for mode in modes:
                started = perf_counter()
                vector = embeddings.encode([redact_contact(question)])[0] if mode == "hybrid" else None
                result = search(conn, company, question, kind=kind, product=product, version=version,
                                vector=vector, model=embeddings.model if embeddings else "")
                metrics[mode, language].append((expected, [row["id"] for row in result],
                                                (perf_counter() - started) * 1000))
    if not metrics:
        raise ValueError("Evaluation file is empty.")
    summary: dict[str, dict] = defaultdict(dict)
    for (mode, language), rows in sorted(metrics.items()):
        positive = [(expected, hits) for expected, hits, _ in rows if expected]
        unanswered = [hits for expected, hits, _ in rows if not expected]
        summary[mode][language] = {
            "answerable_cases": len(positive),
            "unanswerable_cases": len(unanswered),
            "recall_at_3": sum(expected in hits for expected, hits in positive) / len(positive) if positive else None,
            "top_1": sum(expected in hits[:1] for expected, hits in positive) / len(positive) if positive else None,
            "no_retrieval_rate": sum(not hits for hits in unanswered) / len(unanswered) if unanswered else None,
            "median_retrieval_ms": round(median(row[2] for row in rows), 2),
        }
    return dict(summary)
