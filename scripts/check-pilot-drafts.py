"""Compare pilot retrieval on draft questions without writing to the approval database."""

import argparse
from collections import defaultdict
import csv
import json
import math
from pathlib import Path
from urllib.parse import urlsplit

from company_ai.mvp.knowledge import MIN_MATCH_MARGIN, Embeddings, grams, lexical_score, match_score, read_jsonl
from company_ai.mvp.policy import requires_procedure


def read_sheet(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def cosine(left: list[float], right: list[float]) -> float:
    return math.fsum(a * b for a, b in zip(left, right, strict=True)) / (math.hypot(*left) * math.hypot(*right))


def acceptance(ranked: list[tuple[str, float]]) -> str | None:
    if not ranked or (len(ranked) > 1 and ranked[0][1] - ranked[1][1] < MIN_MATCH_MARGIN):
        return None
    return ranked[0][0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("review", type=Path)
    parser.add_argument("cases", type=Path)
    parser.add_argument("--local-embeddings")
    parser.add_argument("--model", default="bge-m3")
    args = parser.parse_args()
    model = None
    if args.local_embeddings:
        parsed = urlsplit(args.local_embeddings)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1"} or parsed.username or parsed.password:
            parser.error("Draft questions can only be tested against a loopback embedding endpoint.")
        model = Embeddings(args.local_embeddings, args.model)

    batch = {r["candidate_id"]: r["pilot_id"] for r in read_sheet(args.review)
             if r["company"] == "MAQSU" and r["review_priority"] == "FIRST_BATCH"}
    variants = defaultdict(set)
    for row in read_jsonl(args.bundle / "question_variants.jsonl"):
        if row["company_id"] == "MAQSU" and row["canonical_answer_id"] in batch:
            variants[batch[row["canonical_answer_id"]]].add(row["question"])
    expected_ids = set(batch.values())
    if not expected_ids or set(variants) != expected_ids:
        parser.error("The first batch must have source variants for every candidate.")

    texts = sorted(set().union(*variants.values()))
    vectors = {}
    if model:
        for start in range(0, len(texts), 24):
            chunk = texts[start:start + 24]
            vectors.update(zip(chunk, model.encode(chunk), strict=True))

    results = []
    for case in read_sheet(args.cases):
        expected = case["expected_candidate_if_approved"]
        if expected not in expected_ids and case["case"] not in {"GAP-02", "EVIDENCE-01"}:
            continue
        question = case["prompt_or_test_step"]
        if question.startswith("After "):
            question = question.partition(": ")[2]
        query_grams = grams(question)
        query_vector = model.encode([question])[0] if model else None
        lexical_ranks = []
        hybrid_ranks = []
        for identifier, questions in variants.items():
            lexical_max = 0.0
            hybrid_max = 0.0
            for wording in questions:
                lexical = lexical_score(question, wording, query_grams)
                lexical_max = max(lexical_max, match_score(lexical, 0.0))
                if query_vector is not None:
                    semantic = cosine(query_vector, vectors[wording])
                    hybrid_max = max(hybrid_max, match_score(lexical, semantic))
            if lexical_max:
                lexical_ranks.append((identifier, lexical_max))
            if hybrid_max:
                hybrid_ranks.append((identifier, hybrid_max))
        lexical_ranks.sort(key=lambda item: (-item[1], item[0]))
        hybrid_ranks.sort(key=lambda item: (-item[1], item[0]))
        results.append({
            "case": case["case"], "language": case["language"], "expected": expected,
            "routed_to_procedure": requires_procedure(question),
            "lexical_candidate": acceptance(lexical_ranks),
            "hybrid_candidate": acceptance(hybrid_ranks),
            "hybrid_top_three": [(identifier, round(score, 3)) for identifier, score in hybrid_ranks[:3]],
        })
    if not results:
        parser.error("No draft cases reference the first review batch.")
    print(json.dumps({
        "scope": "offline draft diagnostic",
        "embedding_model": model.model if model else None,
        "question_variants": len(texts),
        "cases": results,
    }, indent=2))


if __name__ == "__main__":
    main()
