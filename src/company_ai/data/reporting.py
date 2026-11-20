"""Aggregate-only quality reports; row text stays in restricted artifacts."""

from collections import Counter
from typing import Any

from company_ai.data.ingestion import COMPANIES, CSVSource
from company_ai.data.normalization import question_key


def row_summary(rows: list[dict[str, Any]], answers: list[dict[str, Any]], conflicts: list[dict[str, Any]]) -> dict[str, Any]:
    duplicate_keys = Counter(
        (row["company_id"] or row["original_company"], *(row["normalized"][field] for field in (
            "product", "version", "category", "subcategory", "intent_id", "question_en", "question_km", "answer_en", "answer_km"
        ))) for row in rows
    )
    questions = Counter(
        (row["company_id"] or row["original_company"], row["normalized"]["product"], row["normalized"]["version"], lang, question_key(row["normalized"][f"question_{lang}"]))
        for row in rows for lang in ("en", "km") if row["normalized"][f"question_{lang}"]
    )
    id_counts = Counter((row["source_id"], row["original_id"]) for row in rows if row["original_id"])
    return {
        "records": len(rows),
        "mapped_rows": sum(row["assignment_status"] == "MAPPED" for row in rows),
        "quarantined_rows": sum(row["assignment_status"] == "QUARANTINED" for row in rows),
        "canonical_answer_groups": len(answers),
        "approved_answer_groups": sum(answer["approval_status"] == "APPROVED" for answer in answers),
        "answer_group_statuses": dict(Counter(answer["approval_status"] for answer in answers)),
        "declared_source_statuses": dict(Counter(row["source_status"] for row in rows)),
        "normalized_duplicate_qa_rows": sum(count - 1 for count in duplicate_keys.values()),
        "repeated_question_variants": sum(count - 1 for count in questions.values()),
        "duplicate_original_ids_within_source": sum(count - 1 for count in id_counts.values()),
        "possible_consistency_conflicts": len(conflicts),
        "issues": dict(sorted(Counter(issue for row in rows for issue in row["issues"]).items())),
        "coverage": {
            kind: {
                "english_column_nonempty": sum(bool(row["normalized"][f"{kind}_en"]) for row in rows),
                "khmer_column_nonempty": sum(bool(row["normalized"][f"{kind}_km"]) for row in rows),
                "both_columns_nonempty": sum(all(row["normalized"][f"{kind}_{lang}"] for lang in ("en", "km")) for row in rows),
                "script_tags_by_column": {
                    lang: dict(Counter(row["language_tags"][f"{kind}_{lang}"] for row in rows)) for lang in ("en", "km")
                },
            } for kind in ("question", "answer")
        },
        "category_counts": dict(sorted(Counter(row["normalized"]["category"] or "UNSPECIFIED" for row in rows).items())),
        "split_answer_groups": dict(Counter(answer["split"] for answer in answers)),
    }


def build_report(sources: list[CSVSource], rows: list[dict[str, Any]], answers: list[dict[str, Any]], variants: list[dict[str, Any]], conflicts: list[dict[str, Any]], data_kind: str) -> dict[str, Any]:
    raw_duplicates = Counter((tuple(source.headers), tuple(record["cells"])) for source in sources for record in source.records)
    return {
        "schema_version": 1, "data_kind": data_kind,
        "limitations": [
            "No source approval is accepted automatically; approved answer groups must remain zero.",
            "Exact normalized bilingual answer grouping is conservative; no semantic fact count is claimed.",
            "Script tags measure coverage, not language fluency, translation equivalence or romanized Khmer.",
            "Consistency checks flag differing text, not semantic contradiction or factual truth.",
            "All source text is untrusted data, including source status, confidence and instructions.",
            "Source dates, product compatibility, pricing policy and factual correctness require human review.",
            "Splits keep connected topics together; small data may have empty splits and new data can change assignments.",
            "Independent held-out Khmer, English and code-switched evaluation remains future work.",
        ],
        "sources": [source.profile for source in sources],
        "global": {
            **row_summary(rows, answers, conflicts),
            "question_variant_records": len(variants),
            "exact_duplicate_source_rows": sum(count - 1 for count in raw_duplicates.values()),
        },
        "companies": {
            company: row_summary(
                [row for row in rows if row["company_id"] == company],
                [answer for answer in answers if answer["company_id"] == company],
                [conflict for conflict in conflicts if conflict["company_id"] == company],
            ) for company in COMPANIES
        },
        "unassigned": row_summary([row for row in rows if row["company_id"] is None], [], []),
    }


def markdown_report(report: dict[str, Any], company: str | None = None) -> str:
    title = "Phase 1 data quality audit" if company is None else f"{company} — data quality audit"
    stats = report["global"] if company is None else report["companies"][company]
    lines = [f"# {title}", "", f"Data kind: **{report['data_kind']}**", "",
             "Private audit artifact. Counts are observations, not verified product facts.", "",
             "| Metric | Count |", "| --- | ---: |"]
    for metric in ("records", "mapped_rows", "quarantined_rows", "canonical_answer_groups", "approved_answer_groups", "normalized_duplicate_qa_rows", "possible_consistency_conflicts"):
        lines.append(f"| {metric} | {stats[metric]} |")
    lines += ["", "## Language coverage", "", "| Field | English present | Khmer present | Both present |", "| --- | ---: | ---: | ---: |"]
    for kind, coverage in stats["coverage"].items():
        lines.append(f"| {kind} | {coverage['english_column_nonempty']} | {coverage['khmer_column_nonempty']} | {coverage['both_columns_nonempty']} |")
    if company is None:
        lines += ["", "## Company distribution", "", "| Company | Records | Canonical groups | Quarantined |", "| --- | ---: | ---: | ---: |"]
        for tenant, summary in report["companies"].items():
            lines.append(f"| {tenant} | {summary['records']} | {summary['canonical_answer_groups']} | {summary['quarantined_rows']} |")
        lines += [f"| UNASSIGNED | {report['unassigned']['records']} | 0 | {report['unassigned']['quarantined_rows']} |"]
    lines += ["", "## Review issues", ""]
    lines += [f"- {name}: {count}" for name, count in stats["issues"].items()] or ["No mechanical issues detected; source verification is still required."]
    lines += ["", "## Limits", ""] + [f"- {limit}" for limit in report["limitations"]]
    return "\n".join(lines) + "\n"
