"""Operator commands kept out of the customer API."""

import argparse
import csv
from datetime import date
import json
import os
from pathlib import Path
import sys
from uuid import UUID

import httpx
import psycopg

from company_ai.data.ingestion import COMPANIES
from company_ai.mvp.app import configured_embeddings
from company_ai.mvp.db import company_transaction, grant_runtime, migrate
from company_ai.mvp.evaluation import evaluate
from company_ai.mvp.knowledge import import_knowledge, read_jsonl, review_record, reviewed_audit_rows


def seed_demo(dsn: str) -> int:
    with psycopg.connect(dsn) as conn:
        if not conn.info.dbname.endswith("_demo"):
            raise ValueError("Use a separate database whose name ends with _demo for synthetic records.")
    rows = []
    for company in COMPANIES:
        rows.append(review_record(
            company=company, identifier="demo-label", en="This demo uses a sample label for the example record.",
            km="ការសាកល្បងនេះប្រើស្លាកគំរូសម្រាប់កំណត់ត្រាគំរូ។",
            citation="Synthetic demo fixture", reviewer="Synthetic fixture", reviewed_on=date.today().isoformat(),
            questions=("What is the sample label?", "What is the demo label?",
                       "តើស្លាកគំរូជាអ្វី?", "តើ demo label ជាអ្វី?"),
            public_question_en="What is the sample label?",
            public_question_km="តើស្លាកគំរូជាអ្វី?",
        ))
        rows.append(review_record(
            company=company, identifier="demo-guide", kind="procedure", product="demo", version="1",
            en="For this synthetic exercise, select the sample label and confirm it in the example record.",
            km="សម្រាប់លំហាត់សាកល្បងនេះ សូមជ្រើសស្លាកគំរូ ហើយបញ្ជាក់វានៅក្នុងកំណត់ត្រាគំរូ។",
            citation="Synthetic demo guide, version 1", reviewer="Synthetic fixture",
            reviewed_on=date.today().isoformat(),
            questions=("How do I select the sample label?", "តើខ្ញុំជ្រើសស្លាកគំរូដោយរបៀបណា?"),
        ))
    return import_knowledge(dsn, rows)


def import_manuals(dsn: str, path: Path) -> int:
    records = []
    for record in read_jsonl(path):
        if record.pop("decision", "") != "APPROVED":
            continue
        if record.get("kind") != "procedure":
            raise ValueError("A manual entry must be a versioned procedure.")
        if not isinstance(record.get("questions"), list) or not all(isinstance(q, str) for q in record["questions"]):
            raise ValueError("Manual questions must be an array of strings.")
        records.append(review_record(**record))
    return import_knowledge(dsn, records, configured_embeddings())


def company_report(dsn: str, company: str) -> dict:
    with company_transaction(dsn, company) as conn:
        return conn.execute("""
            SELECT (SELECT count(*) FROM knowledge WHERE company_id=%s AND status='APPROVED') AS approved,
                   (SELECT count(*) FROM leads WHERE company_id=%s) AS leads,
                   (SELECT count(*) FROM knowledge_gaps WHERE company_id=%s) AS knowledge_gaps
        """, (company, company, company)).fetchone()


def export_leads(dsn: str, company: str, output: Path) -> int:
    if not output.resolve().is_relative_to(Path("data/processed").resolve()):
        raise ValueError("Export to a new CSV under the private data/processed directory.")
    with company_transaction(dsn, company) as conn:
        rows = conn.execute("""
            SELECT id, company_id, name, channel, contact, business_type, modules, consented_at, created_at
            FROM leads WHERE company_id=%s ORDER BY created_at
        """, (company,)).fetchall()
    with output.open("x", encoding="utf-8-sig", newline="") as stream:
        os.fchmod(stream.fileno(), 0o600)
        columns = ["id", "company_id", "name", "channel", "contact",
                   "business_type", "modules", "consented_at", "created_at"]
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: "'" + value if isinstance(value, str) and
                             value.lstrip().startswith(("=", "+", "-", "@")) else value
                             for key, value in row.items()})
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local company assistant operations")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate")
    role = commands.add_parser("grant-runtime")
    role.add_argument("role")
    commands.add_parser("seed-demo")
    reviews = commands.add_parser("import-reviews")
    reviews.add_argument("bundle", type=Path)
    reviews.add_argument("review_csv", type=Path)
    manuals = commands.add_parser("import-manuals")
    manuals.add_argument("reviewed_procedures", type=Path)
    report = commands.add_parser("summary")
    report.add_argument("company", choices=COMPANIES)
    revoke = commands.add_parser("revoke")
    revoke.add_argument("company", choices=COMPANIES)
    revoke.add_argument("candidate_id")
    leads = commands.add_parser("export-leads")
    leads.add_argument("company", choices=COMPANIES)
    leads.add_argument("output", type=Path)
    delete = commands.add_parser("delete-lead")
    delete.add_argument("company", choices=COMPANIES)
    delete.add_argument("reference", type=UUID)
    benchmark = commands.add_parser("evaluate")
    benchmark.add_argument("cases", type=Path)
    cleanup = commands.add_parser("cleanup")
    cleanup.add_argument("company", choices=COMPANIES)
    cleanup.add_argument("--gap-days", type=int, default=30, choices=range(1, 366), metavar="1-365")
    args = parser.parse_args(argv)
    dsn_variable = "COMPANY_AI_DATABASE_URL" if args.command == "evaluate" else "COMPANY_AI_ADMIN_DATABASE_URL"
    dsn = os.environ.get(dsn_variable)
    if not dsn:
        parser.error(f"Set {dsn_variable} for this command.")
    result = {"status": "ok"}
    try:
        if args.command == "migrate":
            migrate(dsn)
        elif args.command == "grant-runtime":
            grant_runtime(dsn, args.role)
        elif args.command == "seed-demo":
            result["synthetic_answers"] = seed_demo(dsn)
        elif args.command == "import-reviews":
            result["published"] = import_knowledge(
                dsn, reviewed_audit_rows(args.bundle, args.review_csv), configured_embeddings(),
            )
        elif args.command == "import-manuals":
            result["published"] = import_manuals(dsn, args.reviewed_procedures)
        elif args.command == "summary":
            result.update(company_report(dsn, args.company))
        elif args.command == "export-leads":
            result["exported"] = export_leads(dsn, args.company, args.output)
        elif args.command == "delete-lead":
            with company_transaction(dsn, args.company) as conn:
                result["deleted"] = conn.execute(
                    "DELETE FROM leads WHERE company_id=%s AND id=%s", (args.company, args.reference),
                ).rowcount
        elif args.command == "evaluate":
            result["retrieval"] = evaluate(dsn, args.cases, configured_embeddings())
        elif args.command == "revoke":
            with company_transaction(dsn, args.company) as conn:
                result["revoked"] = conn.execute("""
                    UPDATE knowledge SET status='REVOKED', reviewed_on=GREATEST(reviewed_on, CURRENT_DATE)
                    WHERE company_id=%s AND id=%s AND status='APPROVED'
                """, (args.company, args.candidate_id)).rowcount
        elif args.command == "cleanup":
            with company_transaction(dsn, args.company) as conn:
                result["expired_sessions"] = conn.execute(
                    "DELETE FROM conversations WHERE company_id=%s AND expires_at <= now()", (args.company,),
                ).rowcount
                result["old_gaps"] = conn.execute("""
                    DELETE FROM knowledge_gaps
                    WHERE company_id=%s AND created_at < now() - %s * interval '1 day'
                """, (args.company, args.gap_days)).rowcount
    except (ValueError, OSError, KeyError, TypeError, psycopg.Error, httpx.HTTPError) as exc:
        # Exception details may contain credentials or source contents.
        print(f"Operation failed ({type(exc).__name__}). Check the input and local configuration.", file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
