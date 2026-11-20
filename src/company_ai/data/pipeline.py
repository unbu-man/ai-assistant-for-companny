"""Publish a complete, private artifact bundle only after successful validation."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

from company_ai.data.ingestion import COMPANIES, DataError, load_mapping, read_source, validate_mapping
from company_ai.data.normalization import safe_slug
from company_ai.data.preparation import assign_splits, canonicalize, consistency_conflicts, prepare_rows
from company_ai.data.reporting import build_report, markdown_report


def write_private(path: Path, content: str | bytes) -> None:
    with path.open("xb") as stream:
        os.chmod(path, 0o600)
        stream.write(content.encode("utf-8") if isinstance(content, str) else content)


def write_json(path: Path, value: Any) -> None:
    write_private(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    write_private(path, "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records))


def run_pipeline(inputs: list[Path], output: Path, mapping_path: Path | None = None, data_kind: str = "SOURCE_DATA_UNVERIFIED") -> dict[str, Any]:
    if not inputs:
        raise DataError("At least one input CSV is required.")
    if data_kind not in {"SOURCE_DATA_UNVERIFIED", "SYNTHETIC_FIXTURE"}:
        raise DataError("Unsupported data kind.")
    if len({path.resolve() for path in inputs}) != len(inputs):
        raise DataError("The same input path was supplied more than once.")
    if output.exists() or output.is_symlink():
        raise DataError("Output already exists. Choose a new run directory; no artifacts were overwritten.")
    mapping = load_mapping(mapping_path)
    sources = [read_source(path, index) for index, path in enumerate(inputs)]
    for source in sources:
        validate_mapping(source, mapping)
    rows = prepare_rows(sources, mapping)
    answers, variants = canonicalize(rows)
    conflicts = consistency_conflicts(rows)
    assign_splits(answers, variants)
    report = build_report(sources, rows, answers, variants, conflicts, data_kind)
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    staging = Path(tempfile.mkdtemp(prefix=".phase1-", dir=output.parent))
    try:
        (staging / "sources").mkdir(mode=0o700)
        (staging / "companies").mkdir(mode=0o700)
        # Also protect bundles created outside the recommended ignored data directory.
        write_private(staging / ".gitignore", "*\n")
        for source in sources:
            write_private(staging / "sources" / f"{source.source_id}.csv", source.content)
        write_json(staging / "manifest.json", {
            "schema_version": 1, "data_kind": data_kind,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "mapping": mapping,
            "normalization": "NFC and Unicode whitespace collapse; case and punctuation retained",
            "approval_policy": "Source declarations never grant approval. BOTH remains unassigned.",
            "sources": [{**source.profile, "snapshot": f"sources/{source.source_id}.csv"} for source in sources],
            "row_count": len(rows), "canonical_answer_groups": len(answers),
        })
        write_jsonl(staging / "raw_records.jsonl", [record for source in sources for record in source.records])
        write_jsonl(staging / "normalized_rows.jsonl", rows)
        write_jsonl(staging / "canonical_answers.jsonl", answers)
        write_jsonl(staging / "question_variants.jsonl", variants)
        write_jsonl(staging / "consistency_conflicts.jsonl", conflicts)
        write_jsonl(staging / "review_queue.jsonl", [{
            "row_id": row["id"], "source_id": row["source_id"], "company_id": row["company_id"],
            "canonical_answer_id": row["canonical_answer_id"],
            "assignment_status": row["assignment_status"], "approval_status": row["approval_status"],
            "issues": row["issues"],
        } for row in rows])
        write_json(staging / "report.json", report)
        write_private(staging / "report.md", markdown_report(report))
        for company in COMPANIES:
            slug = safe_slug(company)
            write_json(staging / "companies" / f"{slug}.json", {
                "data_kind": data_kind, "company_id": company,
                "summary": report["companies"][company], "limitations": report["limitations"],
            })
            write_private(staging / "companies" / f"{slug}.md", markdown_report(report, company))
        if output.exists() or output.is_symlink():
            raise DataError("Output appeared during preparation; nothing was overwritten.")
        staging.rename(output)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return report
