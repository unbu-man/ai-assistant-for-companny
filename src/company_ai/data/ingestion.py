"""Strict UTF-8 CSV ingestion with exact cell and byte provenance."""

from collections import Counter
import csv
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
from typing import Any

from company_ai.data.normalization import language_tag, normalize

COMPANIES = ("MAQSU", "CLOSO", "GIANTFOCUS", "FALCORA", "ClickHR", "GIANTBROTHER")
FIELDS = (
    "id", "company", "category", "subcategory", "question_en", "question_km",
    "answer_en", "answer_km", "keywords_en", "keywords_km", "source_document",
    "source_section", "intent_id", "confidence", "status", "product", "version",
)
DEFAULT_MAPPING = {field: field for field in FIELDS}


class DataError(ValueError):
    """Actionable error that does not include confidential cell contents."""


def stable_id(prefix: str, value: Any) -> str:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return prefix + hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def load_mapping(path: Path | None) -> dict[str, str]:
    mapping = dict(DEFAULT_MAPPING)
    if path is not None:
        try:
            custom = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise DataError("Mapping must be a UTF-8 JSON object.") from exc
        if not isinstance(custom, dict) or any(
            key not in FIELDS or not isinstance(value, str) or not value
            for key, value in custom.items()
        ):
            raise DataError("Mapping keys must be supported field names and values nonempty column names.")
        mapping.update(custom)
    if len(set(mapping.values())) != len(mapping):
        raise DataError("Each logical field must map to a distinct CSV column.")
    return mapping


@dataclass
class CSVSource:
    path: Path
    content: bytes
    source_id: str
    sha256: str
    headers: list[str]
    records: list[dict[str, Any]]
    profile: dict[str, Any]


def read_source(path: Path, index: int = 0) -> CSVSource:
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    source_id = stable_id("src_", [index, path.name, digest])
    try:
        decoded = content.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise DataError("Input is not valid UTF-8. Convert a COPY explicitly; retain the original.") from exc
    reader = csv.reader(io.StringIO(decoded, newline=""), strict=True)
    try:
        headers = next(reader)
    except StopIteration as exc:
        raise DataError("CSV is empty; a header is required.") from exc
    except csv.Error as exc:
        raise DataError("Invalid CSV header; repair a copy explicitly.") from exc
    # Fail rather than silently overwrite duplicate/blank column names in a dict.
    if not headers or any(not header.strip() for header in headers) or len(set(headers)) != len(headers):
        raise DataError("CSV header has blank or duplicate names; repair a copy explicitly.")
    records: list[dict[str, Any]] = []
    last_line = reader.line_num
    try:
        for ordinal, cells in enumerate(reader, start=1):
            records.append({
                "id": stable_id("row_", [source_id, ordinal]),
                "source_id": source_id,
                "record_number": ordinal,
                "physical_line_start": last_line + 1,
                "physical_line_end": reader.line_num,
                "cells": cells,
                "structural_valid": len(cells) == len(headers),
            })
            last_line = reader.line_num
    except csv.Error as exc:
        raise DataError(f"Malformed CSV near physical line {reader.line_num}; no output published.") from exc
    profiles = []
    for column_index, header in enumerate(headers):
        values = [record["cells"][column_index] if column_index < len(record["cells"]) else "" for record in records]
        profiles.append({
            "name": header,
            "nonempty": sum(bool(normalize(value)) for value in values),
            "empty_or_missing": sum(not normalize(value) for value in values),
            "distinct_nonempty": len({normalize(value) for value in values if normalize(value)}),
            "max_characters": max(map(len, values), default=0),
            "normalization_changes": sum(value != normalize(value) for value in values),
            "script_coverage": dict(Counter(language_tag(value) for value in values)),
        })
    profile = {
        "source_id": source_id, "filename": path.name, "sha256": digest,
        "byte_count": len(content), "utf8_bom": content.startswith(b"\xef\xbb\xbf"),
        "headers": headers, "record_count": len(records),
        "structural_error_rows": sum(not row["structural_valid"] for row in records),
        "columns": profiles,
    }
    return CSVSource(path, content, source_id, digest, headers, records, profile)


def validate_mapping(source: CSVSource, mapping: dict[str, str]) -> None:
    present = set(source.headers)
    if mapping["company"] not in present:
        raise DataError("Company column is missing; inspect the headers and provide --mapping.")
    for kind in ("question", "answer"):
        if not any(mapping[f"{kind}_{language}"] in present for language in ("en", "km")):
            raise DataError(f"No {kind} column found; inspect the headers and provide --mapping.")
