"""Import only explicit reviewer decisions and search the resulting company index."""

from collections import defaultdict
from collections.abc import Iterable
import csv
from datetime import date
import json
import math
from pathlib import Path
import re
from typing import Any
import unicodedata

import httpx
import psycopg

from company_ai.data.ingestion import COMPANIES
from company_ai.data.normalization import language_tag, normalize
from company_ai.mvp.db import company_transaction
from company_ai.mvp.policy import (
    intent_text, mentions_other_company, redact_contact, requests_price, requires_procedure, unsafe_evidence,
)

LEXICAL_MINIMUM = 0.46
SEMANTIC_MINIMUM = 0.68
MIN_MATCH_MARGIN = 0.09


def match_score(lexical: float, semantic: float) -> float:
    if lexical < LEXICAL_MINIMUM and semantic < SEMANTIC_MINIMUM:
        return 0.0
    return max(lexical, semantic) + 0.08 * min(lexical, semantic)


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)


def verified_text(value: str, label: str) -> str:
    if not isinstance(value, str) or not normalize(value):
        raise ValueError(f"Missing {label} in review record.")
    return value.strip()


def safe_public_question(company: str, question: str) -> bool:
    return bool(0 < len(question) <= 180
                and not (requests_price(question) or requires_procedure(question)
                         or mentions_other_company(company, question)
                         or redact_contact(question) != question))


def review_record(
    *, company: str, identifier: str, en: str, km: str, citation: str,
    reviewer: str, reviewed_on: str, questions: Iterable[str],
    kind: str = "faq", product: str = "", version: str = "",
    public_question_en: str = "", public_question_km: str = "",
) -> dict[str, Any]:
    if company not in COMPANIES:
        raise ValueError("Review must bind to one company.")
    if kind not in ("faq", "procedure") or (kind == "procedure" and not (product.strip() and version.strip())):
        raise ValueError("Procedures must specify reviewed product and version.")
    if any(unsafe_evidence(value) for value in (en, km, citation)):
        raise ValueError("Review contains pricing-like evidence. Remove it and review the revised answer.")
    if any(mentions_other_company(company, value) for value in (en, km, citation)):
        raise ValueError("A reviewed response and public citation must be scoped to its own company.")
    reviewed = date.fromisoformat(reviewed_on)
    if reviewed > date.today():
        raise ValueError("Review date cannot be in the future.")
    wordings = sorted({normalize(value) for value in questions if normalize(value)})
    if not wordings:
        raise ValueError("A reviewer-approved answer requires a question.")
    question_en, question_km = map(normalize, (public_question_en, public_question_km))
    if question_en or question_km:
        if (kind != "faq" or product.strip() or version.strip()
                or not all(safe_public_question(company, question) for question in (question_en, question_km))
                or language_tag(question_en) not in {"latin_script", "mixed_km_latin"}
                or language_tag(question_km) not in {"km_script", "mixed_km_latin"}):
            raise ValueError("Public questions must be safe, bilingual labels for a general FAQ.")
    return {
        "company_id": company, "id": verified_text(identifier, "candidate ID"),
        "kind": kind, "product": normalize(product).casefold(), "version": normalize(version).casefold(),
        "answer_en": verified_text(en, "English answer"), "answer_km": verified_text(km, "Khmer answer"),
        "citation": verified_text(citation, "verified citation"), "reviewer": verified_text(reviewer, "reviewer"),
        "reviewed_on": reviewed, "questions": wordings,
        "public_question_en": question_en or None, "public_question_km": question_km or None,
    }


def reviewed_audit_rows(bundle: Path, review_csv: Path) -> list[dict[str, Any]]:
    candidates = {row["id"]: row for row in read_jsonl(bundle / "canonical_answers.jsonl")}
    variants: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in read_jsonl(bundle / "question_variants.jsonl"):
        variants[row["company_id"], row["canonical_answer_id"]].append(row["question"])
    records = []
    seen = set()
    with review_csv.open(encoding="utf-8-sig", newline="") as stream:
        for decision in csv.DictReader(stream):
            if decision.get("review_decision", "").strip().upper() != "APPROVED":
                continue
            company = decision["company"]
            identifier = decision["candidate_id"]
            candidate = candidates.get(identifier)
            if (candidate is None or candidate["company_id"] != company
                    or candidate["approval_status"] != "NEEDS_REVIEW" or identifier in seen):
                raise ValueError("Invalid, rejected, repeated, or wrong-company review target.")
            seen.add(identifier)
            # Reviewers may correct the wording in the sheet before approving it.
            records.append(review_record(
                company=company, identifier=identifier, en=decision["candidate_answer_en"],
                km=decision["candidate_answer_km"], citation=decision["verified_source_and_section"],
                reviewer=decision["reviewer"], reviewed_on=decision["reviewed_date"],
                questions=variants[company, identifier],
                public_question_en=decision.get("public_question_en") or "",
                public_question_km=decision.get("public_question_km") or "",
            ))
    return records


class Embeddings:
    """Opt-in HTTP model adapter using the OpenAI-compatible embeddings shape."""

    def __init__(self, base_url: str, model: str, key: str = ""):
        self.url = base_url.rstrip("/") + "/embeddings"
        self.model = model
        self.key = key

    def encode(self, texts: list[str]) -> list[list[float]]:
        headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
        response = httpx.post(
            self.url, json={"model": self.model, "input": texts}, headers=headers, timeout=12,
            trust_env=False,
        )
        response.raise_for_status()
        items = sorted(response.json()["data"], key=lambda item: item["index"])
        if [item["index"] for item in items] != list(range(len(texts))):
            raise ValueError("Unexpected embedding response indexes.")
        vectors = [item["embedding"] for item in items]
        if any(not vector or len(vector) > 4096 or not all(
            isinstance(item, (int, float)) and math.isfinite(item) and abs(item) < 1e20 for item in vector
        ) or not any(vector) for vector in vectors):
            raise ValueError("Invalid model embedding.")
        return vectors


def import_knowledge(dsn: str, records: list[dict[str, Any]], embeddings: Embeddings | None = None) -> int:
    if len({(record["company_id"], record["id"]) for record in records}) != len(records):
        raise ValueError("Duplicate review ID in input.")
    if not records:
        return 0
    # Finish model work before starting the mutation so a failed request cannot partially publish.
    indexed = []
    for record in records:
        words = record["questions"]
        vectors = []
        if embeddings is not None:
            for start in range(0, len(words), 32):
                vectors.extend(embeddings.encode(words[start:start + 32]))
        indexed.append((record, vectors or [None] * len(words)))
    with company_transaction(dsn, records[0]["company_id"]) as conn:
        for record, vectors in indexed:
            company = record["company_id"]
            conn.execute("SELECT set_config('company_ai.tenant', %s, true)", (company,))
            changed = conn.execute("""
                INSERT INTO knowledge (company_id, id, kind, product, version, answer_en, answer_km,
                    citation, reviewer, reviewed_on, public_question_en, public_question_km, status)
                VALUES (%(company_id)s, %(id)s, %(kind)s, %(product)s, %(version)s, %(answer_en)s,
                    %(answer_km)s, %(citation)s, %(reviewer)s, %(reviewed_on)s,
                    %(public_question_en)s, %(public_question_km)s, 'APPROVED')
                ON CONFLICT (company_id, id) DO UPDATE SET kind=excluded.kind, product=excluded.product,
                    version=excluded.version, answer_en=excluded.answer_en, answer_km=excluded.answer_km,
                    citation=excluded.citation, reviewer=excluded.reviewer, reviewed_on=excluded.reviewed_on,
                    public_question_en=excluded.public_question_en, public_question_km=excluded.public_question_km,
                    status='APPROVED'
                WHERE knowledge.reviewed_on < excluded.reviewed_on OR
                    (knowledge.reviewed_on = excluded.reviewed_on AND knowledge.status = 'APPROVED')
            """, record)
            if changed.rowcount != 1:
                raise ValueError("A revoked decision requires a newer review.")
            conn.execute("DELETE FROM questions WHERE company_id=%s AND knowledge_id=%s", (company, record["id"]))
            with conn.cursor() as cursor:
                cursor.executemany("""
                    INSERT INTO questions (company_id, knowledge_id, wording, embedding_model, embedding)
                    VALUES (%s, %s, %s, %s, %s::vector)
                """, [(company, record["id"], word, embeddings.model if embeddings else None,
                       json.dumps(vector) if vector is not None else None)
                      for word, vector in zip(record["questions"], vectors, strict=True)])
    return len(records)


def public_topics(conn: psycopg.Connection, company: str) -> list[dict[str, str]]:
    rows = conn.execute("""
        SELECT id, public_question_en AS en, public_question_km AS km FROM knowledge
        WHERE company_id=%s AND status='APPROVED' AND kind='faq' AND product='' AND version=''
          AND public_question_en IS NOT NULL AND public_question_km IS NOT NULL
        ORDER BY public_question_en, id LIMIT 24
    """, (company,)).fetchall()
    return [row for row in rows if all(safe_public_question(company, row[lang]) for lang in ("en", "km"))]


def grams(text: str) -> set[str]:
    normalized = "".join(
        char for char in intent_text(text).casefold() if unicodedata.category(char)[0] in "LMN"
    )
    return {normalized[i:i + 3] for i in range(len(normalized) - 2)}


def lexical_score(query: str, wording: str, query_grams: set[str]) -> float:
    if intent_text(query).casefold() == intent_text(wording).casefold():
        return 1.0
    other = grams(wording)
    if not query_grams or not other:
        return 0.0
    return 2 * len(query_grams & other) / (len(query_grams) + len(other))


def search(
    conn: psycopg.Connection, company: str, query: str, *,
    kind: str = "faq", product: str = "", version: str = "",
    vector: list[float] | None = None, model: str = "",
    limit: int = 3,
) -> list[dict[str, Any]]:
    encoded = json.dumps(vector) if vector is not None else None
    rows = conn.execute("""
        SELECT k.id, k.answer_en, k.answer_km, k.citation, q.wording,
            CASE WHEN q.embedding_model = %(model)s
                    AND vector_dims(q.embedding) = vector_dims(%(vector)s::vector)
                THEN 1 - (q.embedding <=> %(vector)s::vector) END AS semantic
        FROM knowledge k
        JOIN questions q ON q.company_id = k.company_id AND q.knowledge_id = k.id
        WHERE k.company_id = %(company)s AND k.status = 'APPROVED' AND k.kind = %(kind)s
            AND (k.product = '' OR k.product = %(product)s)
            AND (k.version = '' OR k.version = %(version)s)
    """, {"company": company, "kind": kind, "product": product, "version": version,
          "model": model, "vector": encoded}).fetchall()
    query_grams = grams(query)
    best = {}
    for row in rows:
        lexical = lexical_score(query, row["wording"], query_grams)
        semantic = row["semantic"] or 0.0
        score = match_score(lexical, semantic)
        if not score:
            continue
        previous = best.get(row["id"])
        if previous is None or score > previous["score"]:
            best[row["id"]] = {
                key: row[key] for key in ("id", "answer_en", "answer_km", "citation")
            } | {"score": score}
    return sorted(best.values(), key=lambda row: (-row["score"], row["id"]))[:limit]
