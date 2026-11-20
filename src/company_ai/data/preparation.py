"""Tenant resolution, review quarantine and exact-answer grouping."""

from collections import Counter, defaultdict
from typing import Any

from company_ai.data.ingestion import COMPANIES, CSVSource, stable_id
from company_ai.data.normalization import has_control_characters, language_tag, normalize, question_key


def prepare_rows(sources: list[CSVSource], mapping: dict[str, str]) -> list[dict[str, Any]]:
    rows = []
    companies = {company.casefold(): company for company in COMPANIES}
    for source in sources:
        for record in source.records:
            fields = dict(zip(source.headers, record["cells"]))
            normalized = {field: normalize(fields.get(column, "")) for field, column in mapping.items()}
            label = normalized["company"]
            tenant = companies.get(label.casefold())
            issues: list[str] = []
            blockers: list[str] = []
            if not record["structural_valid"]:
                blockers.append("column_count_mismatch")
            if tenant is None:
                blockers.append("shared_company_requires_explicit_approval" if label.casefold() == "both" else "unresolved_company")
            for kind in ("question", "answer"):
                if not any(normalized[f"{kind}_{lang}"] for lang in ("en", "km")):
                    blockers.append(f"missing_{kind}")
            if not normalized["source_document"]:
                issues.append("missing_source_document")
            if any(has_control_characters(value) for value in fields.values()):
                blockers.append("unexpected_control_character")
            source_status = normalized["status"].upper() or "UNSPECIFIED"
            if source_status not in {"UNSPECIFIED", "APPROVED", "NEEDS_REVIEW", "REJECTED", "DRAFT"}:
                issues.append("unknown_source_status")
            if source_status == "APPROVED":
                issues.append("source_approval_requires_independent_verification")
            languages = {field: language_tag(normalized[field]) for field in ("question_en", "question_km", "answer_en", "answer_km")}
            for lang, expected in (("en", "latin_script"), ("km", "km_script")):
                for kind in ("question", "answer"):
                    tag = languages[f"{kind}_{lang}"]
                    if tag == "empty":
                        issues.append(f"missing_{kind}_{lang}")
                    elif tag not in {expected, "mixed_km_latin"}:
                        issues.append(f"unexpected_script_{kind}_{lang}")
            rows.append({
                "id": record["id"], "source_id": source.source_id,
                "record_number": record["record_number"], "original_id": normalized["id"],
                "company_id": tenant, "original_company": label,
                "normalized": normalized, "language_tags": languages,
                "source_status": source_status,
                "approval_status": "REJECTED" if source_status == "REJECTED" else "NEEDS_REVIEW",
                "assignment_status": "QUARANTINED" if blockers else "MAPPED",
                "issues": issues + blockers,
                "canonical_answer_id": None,
            })
    return rows


def scope(row: dict[str, Any]) -> tuple[str, ...]:
    values = row["normalized"]
    return (row["company_id"], values["product"], values["version"])


def canonicalize(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["assignment_status"] != "MAPPED":
            continue
        values = row["normalized"]
        key = [*scope(row), *(values[field] for field in ("category", "subcategory", "intent_id", "answer_en", "answer_km"))]
        group_id = stable_id("answer_", key)
        row["canonical_answer_id"] = group_id
        groups[group_id].append(row)
    answers, variants = [], []
    for group_id, members in sorted(groups.items()):
        first = members[0]
        values = first["normalized"]
        answers.append({
            "id": group_id, "company_id": first["company_id"],
            **{field: values[field] for field in ("product", "version", "category", "subcategory", "intent_id", "answer_en", "answer_km")},
            "approval_status": "REJECTED" if any(row["source_status"] == "REJECTED" for row in members) else "NEEDS_REVIEW",
            "row_ids": [row["id"] for row in members],
            "source_ids": sorted({row["source_id"] for row in members}),
            "declared_source_status_counts": dict(Counter(row["source_status"] for row in members)),
            "provenance": [{
                "row_id": row["id"], "source_id": row["source_id"],
                "record_number": row["record_number"], "original_id": row["original_id"],
                "source_document": row["normalized"]["source_document"],
                "source_section": row["normalized"]["source_section"],
                "confidence": row["normalized"]["confidence"],
            } for row in members],
        })
        for row in members:
            for language in ("en", "km"):
                question = row["normalized"][f"question_{language}"]
                if question:
                    variants.append({
                        "id": stable_id("variant_", [row["id"], language]),
                        "company_id": row["company_id"], "canonical_answer_id": group_id,
                        "original_row_id": row["id"], "source_id": row["source_id"],
                        "language_column": language,
                        "language_tag": row["language_tags"][f"question_{language}"], "question": question,
                    })
    return answers, variants


def consistency_conflicts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flag possible contradictions, without deciding which statement is true."""
    indexes: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["assignment_status"] != "MAPPED":
            continue
        values = row["normalized"]
        for lang in ("en", "km"):
            question = question_key(values[f"question_{lang}"])
            if question:
                indexes[(*scope(row), "question", lang, question)].append(row)
        if values["intent_id"]:
            indexes[(*scope(row), "intent", values["intent_id"])].append(row)
    conflicts = []
    for key, members in sorted(indexes.items()):
        answers = {(row["normalized"]["answer_en"], row["normalized"]["answer_km"]) for row in members}
        if len(answers) <= 1:
            continue
        conflict_id = stable_id("conflict_", key)
        conflicts.append({
            "id": conflict_id, "company_id": members[0]["company_id"],
            "kind": "same_question_different_answers" if key[3] == "question" else "same_intent_different_answers",
            "row_ids": [row["id"] for row in members],
            "canonical_answer_ids": sorted({row["canonical_answer_id"] for row in members}),
            "distinct_answer_pairs": len(answers), "status": "NEEDS_REVIEW",
        })
        for row in members:
            if "possible_answer_inconsistency" not in row["issues"]:
                row["issues"].append("possible_answer_inconsistency")
    return conflicts


def assign_splits(answers: list[dict[str, Any]], variants: list[dict[str, Any]]) -> None:
    """Keep connected exact answers, intents, topics and questions in one split.

    Cross-company exact answer pairs share a split but are NEVER merged as data.
    These are preparation assignments, not a held-out quality benchmark.
    """
    parents = {answer["id"]: answer["id"] for answer in answers}

    def root(value: str) -> str:
        while parents[value] != value:
            parents[value] = parents[parents[value]]
            value = parents[value]
        return value

    def connect(first: str, second: str) -> None:
        a, b = sorted((root(first), root(second)))
        parents[b] = a

    seen: dict[tuple[str, ...], str] = {}
    for answer in answers:
        tenant_scope = (answer["company_id"], answer["product"], answer["version"])
        keys = [("answer", answer["answer_en"], answer["answer_km"])]
        if answer["intent_id"]:
            keys.append(("intent", *tenant_scope, answer["intent_id"]))
        if answer["category"]:
            keys.append(("topic", *tenant_scope, answer["category"], answer["subcategory"]))
        for key in keys:
            if key in seen:
                connect(answer["id"], seen[key])
            seen[key] = answer["id"]
    for variant in variants:
        key = ("question", variant["company_id"], question_key(variant["question"]))
        if key in seen:
            connect(variant["canonical_answer_id"], seen[key])
        seen[key] = variant["canonical_answer_id"]
    components: dict[str, list[str]] = defaultdict(list)
    for answer_id in parents:
        components[root(answer_id)].append(answer_id)
    assignments = {}
    for members in components.values():
        group_id = stable_id("split_", sorted(members))
        bucket = int(group_id[-8:], 16) % 100
        split = "train" if bucket < 80 else "dev" if bucket < 90 else "test"
        for member in members:
            assignments[member] = (group_id, split)
    for record in [*answers, *variants]:
        canonical_id = record.get("canonical_answer_id", record["id"])
        record["leakage_group_id"], record["split"] = assignments[canonical_id]
