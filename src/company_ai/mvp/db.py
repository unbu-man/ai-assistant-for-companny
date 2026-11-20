"""Short PostgreSQL transactions with a company scope fixed before any query."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from company_ai.data.ingestion import COMPANIES


def migrate(dsn: str) -> None:
    with psycopg.connect(dsn) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(4749202601)")
        conn.execute(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))


def grant_runtime(dsn: str, role: str) -> None:
    with psycopg.connect(dsn) as conn:
        attributes = conn.execute(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = %s", (role,)
        ).fetchone()
        if attributes is None or any(attributes):
            raise ValueError("Runtime role must exist and cannot bypass row security.")
        grantee = sql.Identifier(role)
        for statement in (
            "GRANT USAGE ON SCHEMA assistant_mvp TO {}",
            "GRANT SELECT ON assistant_mvp.knowledge, assistant_mvp.questions TO {}",
            "GRANT SELECT, INSERT, UPDATE ON assistant_mvp.conversations TO {}",
            "GRANT INSERT ON assistant_mvp.leads, assistant_mvp.knowledge_gaps TO {}",
        ):
            conn.execute(sql.SQL(statement).format(grantee))


@contextmanager
def company_transaction(dsn: str, company: str) -> Iterator[psycopg.Connection]:
    if company not in COMPANIES:
        raise ValueError("Unknown company")
    with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=5) as conn:
        conn.execute("SET LOCAL search_path TO assistant_mvp, public")
        conn.execute("SELECT set_config('company_ai.tenant', %s, true)", (company,))
        yield conn


def ping_runtime(dsn: str) -> None:
    with company_transaction(dsn, COMPANIES[0]) as conn:
        allowed = conn.execute("""
            SELECT NOT (rolsuper OR rolbypassrls)
                AND row_security_active('knowledge')
                AND row_security_active('conversations')
                AND row_security_active('leads')
                AND NOT has_table_privilege(current_user, 'knowledge', 'INSERT')
                AND NOT has_table_privilege(current_user, 'knowledge', 'UPDATE')
                AND NOT has_table_privilege(current_user, 'leads', 'SELECT')
                AS allowed
            FROM pg_roles WHERE rolname = current_user
        """).fetchone()
        if not allowed or not allowed["allowed"]:
            raise RuntimeError("Use a dedicated runtime role with row security and restricted grants.")
