"""FastAPI entry point for the private local pilot."""

from contextlib import asynccontextmanager
import hashlib
import os
from pathlib import Path
import re
import secrets
from typing import Annotated, Literal
from uuid import uuid4

import httpx
import psycopg
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, StringConstraints

from company_ai.data.ingestion import COMPANIES
from company_ai.data.normalization import normalize
from company_ai.mvp.db import company_transaction, ping_runtime
from company_ai.mvp.knowledge import MIN_MATCH_MARGIN, Embeddings, public_topics, safe_public_question, search
from company_ai.mvp.messages import say
from company_ai.mvp.policy import (
    intent_text, mentions_other_company, redact_contact, requests_price, requires_procedure,
    select_language, unsafe_evidence,
)

Language = Literal["en", "km"]
Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
MessageText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=900)]
Auth = Annotated[str | None, Header(alias="Authorization")]
FOLLOW_UP = re.compile(r"^(?:tell me more|more details|what about that|ប្រាប់បន្ថែម|ព័ត៌មានបន្ថែម)[?.!។ ]*$", re.I)


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SessionInput(Input):
    language: Language = "en"


class ChatInput(Input):
    message: MessageText
    language: Language | None = None
    product: Short | None = None
    version: Short | None = None


class TopicInput(Input):
    id: Short
    language: Language


class QuoteScope(Input):
    business_type: Short
    modules: Short


class QuoteConsent(Input):
    consent: bool


class QuoteContact(Input):
    name: Short
    channel: Literal["phone", "telegram"]
    contact: Short


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def authenticate(auth: str | None) -> str:
    match = re.fullmatch(r"Bearer ([A-Za-z0-9_-]{43})", auth or "")
    if not match:
        raise HTTPException(401, "A valid chat session is required.")
    return token_hash(match[1])


def session_row(conn, company: str, hashed: str):
    row = conn.execute("""
        SELECT * FROM conversations WHERE company_id=%s AND token_hash=%s AND expires_at > now()
        FOR UPDATE
    """, (company, hashed)).fetchone()
    if row is None:
        raise HTTPException(404, "Chat session not found or expired.")
    return row


def clear_quote(conn, company: str, hashed: str) -> None:
    conn.execute("""
        UPDATE conversations SET phase='idle', business_type=NULL, modules=NULL, consented_at=NULL
        WHERE company_id=%s AND token_hash=%s
    """, (company, hashed))


def reply(text, language, kind, *, next_action=None, citation=None, reference=None):
    return {"text": text, "language": language, "kind": kind, "next_action": next_action,
            "citation": citation, "reference": reference}


def reviewed_reply(conn, company: str, hashed: str, hit: dict, language: Language):
    answer = hit[f"answer_{language}"]
    if any(unsafe_evidence(value) or mentions_other_company(company, value)
           for value in (answer, hit["citation"])):
        return None
    conn.execute("""
        UPDATE conversations SET last_answer_id=%s, language=%s WHERE company_id=%s AND token_hash=%s
    """, (hit["id"], language, company, hashed))
    return reply(answer, language, "answer", citation=hit["citation"])


def acceptable_contact(data: QuoteContact) -> bool:
    if data.channel == "telegram":
        return re.fullmatch(r"@[A-Za-z][A-Za-z0-9_]{4,31}", data.contact) is not None
    return bool(re.fullmatch(r"\+?[\d ()-]+", data.contact) and 7 <= sum(c.isdecimal() for c in data.contact) <= 15)


def create_app(
    dsn: str, *, fixed_company: str = "", demo: bool = False,
    embeddings: Embeddings | None = None, log_gap_text: bool = False,
) -> FastAPI:
    if fixed_company and fixed_company not in COMPANIES:
        raise ValueError("Invalid configured company.")
    allowed_companies = (fixed_company,) if fixed_company else COMPANIES

    @asynccontextmanager
    async def lifespan(app):
        ping_runtime(dsn)
        yield

    app = FastAPI(
        title="Company Support", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan,
    )

    def tenant(company: str) -> str:
        if company not in allowed_companies:
            raise HTTPException(404, "Company not found on this site.")
        return company

    @app.middleware("http")
    async def headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        return JSONResponse({"detail": "Check the supplied fields and try again."}, status_code=422)

    @app.exception_handler(psycopg.Error)
    async def unavailable(request, exc):
        return JSONResponse({"detail": "Service temporarily unavailable. Please try again."}, status_code=503)

    @app.get("/api/config")
    def config():
        return {"companies": allowed_companies, "demo": demo}

    @app.get("/health")
    def health():
        with company_transaction(dsn, allowed_companies[0]) as conn:
            conn.execute("SELECT 1")
        return {"status": "ok"}

    @app.post("/api/{company}/sessions", status_code=201)
    def start(company: str, data: SessionInput):
        company = tenant(company)
        token = secrets.token_urlsafe(32)
        with company_transaction(dsn, company) as conn:
            conn.execute(
                "INSERT INTO conversations (company_id, token_hash, language) VALUES (%s,%s,%s)",
                (company, token_hash(token), data.language),
            )
            topics = public_topics(conn, company)
        return {"token": token, "welcome": say("welcome", data.language), "topics": topics}

    @app.post("/api/{company}/topic")
    def choose_topic(company: str, data: TopicInput, authorization: Auth = None):
        company, hashed = tenant(company), authenticate(authorization)
        with company_transaction(dsn, company) as conn:
            state = session_row(conn, company, hashed)
            if state["phase"] != "idle":
                raise HTTPException(409, "Finish or cancel the quotation request first.")
            hit = conn.execute("""
                SELECT id, answer_en, answer_km, citation, public_question_en, public_question_km
                FROM knowledge WHERE company_id=%s AND id=%s AND status='APPROVED'
                    AND kind='faq' AND product='' AND version=''
                    AND public_question_en IS NOT NULL AND public_question_km IS NOT NULL
            """, (company, data.id)).fetchone()
            if hit and all(safe_public_question(company, hit[f"public_question_{lang}"])
                           for lang in ("en", "km")):
                result = reviewed_reply(conn, company, hashed, hit, data.language)
                if result:
                    return result
            raise HTTPException(404, "Verified topic not available.")

    @app.post("/api/{company}/chat")
    def chat(company: str, data: ChatInput, authorization: Auth = None):
        company, hashed = tenant(company), authenticate(authorization)
        message = intent_text(data.message)
        if not message:
            raise HTTPException(422, "Enter a question.")
        with company_transaction(dsn, company) as conn:
            state = session_row(conn, company, hashed)
            lang = select_language(message, state["language"], data.language)
            conn.execute(
                "UPDATE conversations SET language=%s WHERE company_id=%s AND token_hash=%s",
                (lang, company, hashed),
            )
            if mentions_other_company(company, message):
                return reply(say("tenant", lang, company=company), lang, "company_boundary")
            if state["phase"] != "idle":
                return reply(say(state["phase"], lang), lang, "quote", next_action=state["phase"])
            if requests_price(message):
                conn.execute(
                    "UPDATE conversations SET phase='scope', last_answer_id=NULL WHERE company_id=%s AND token_hash=%s",
                    (company, hashed),
                )
                return reply(say("scope", lang), lang, "quote", next_action="scope")
            technical = requires_procedure(message)
            product = normalize(data.product or "").casefold()
            version = normalize(data.version or "").casefold()
            hits = []
            if state["last_answer_id"] and FOLLOW_UP.fullmatch(message):
                previous = conn.execute("""
                    SELECT id, answer_en, answer_km, citation FROM knowledge
                    WHERE company_id=%s AND id=%s AND status='APPROVED' AND kind='faq'
                    AND (product='' OR product=%s) AND (version='' OR version=%s)
                """, (company, state["last_answer_id"], product, version)).fetchone()
                if previous:
                    hits = [previous]
            elif not technical or (product and version):
                vector = None
                if embeddings:
                    try:
                        vector = embeddings.encode([redact_contact(message)])[0]
                    except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
                        # The lexical path remains available if the optional provider is down.
                        pass
                hits = search(conn, company, message, kind="procedure" if technical else "faq",
                              product=product, version=version, vector=vector,
                              model=embeddings.model if embeddings else "")
                if len(hits) > 1 and hits[0]["score"] - hits[1]["score"] < MIN_MATCH_MARGIN:
                    hits = []
            if hits:
                result = reviewed_reply(conn, company, hashed, hits[0], lang)
                if result:
                    return result
            reason = "missing_procedure" if technical else "no_supported_match"
            conn.execute("""
                INSERT INTO knowledge_gaps (company_id, language, reason, question)
                VALUES (%s,%s,%s,%s)
            """, (company, lang, reason, redact_contact(message) if log_gap_text else None))
            conn.execute(
                "UPDATE conversations SET last_answer_id=NULL WHERE company_id=%s AND token_hash=%s",
                (company, hashed),
            )
            key = ("procedure_unavailable" if product and version else "procedure_unknown") if technical else "unknown"
            action = "procedure_context" if key == "procedure_unknown" else None
            return reply(say(key, lang), lang, "knowledge_gap", next_action=action)

    @app.post("/api/{company}/quote/scope")
    def scope(company: str, data: QuoteScope, authorization: Auth = None):
        company, hashed = tenant(company), authenticate(authorization)
        if any(redact_contact(value) != value for value in (data.business_type, data.modules)):
            raise HTTPException(422, "Please enter business details without contact information.")
        with company_transaction(dsn, company) as conn:
            state = session_row(conn, company, hashed)
            if state["phase"] != "scope":
                raise HTTPException(409, "Quotation scoping is not active.")
            conn.execute("""
                UPDATE conversations SET phase='consent', business_type=%s, modules=%s
                WHERE company_id=%s AND token_hash=%s
            """, (data.business_type, data.modules, company, hashed))
        return reply(say("consent", state["language"]), state["language"], "quote", next_action="consent")

    @app.post("/api/{company}/quote/consent")
    def consent(company: str, data: QuoteConsent, authorization: Auth = None):
        company, hashed = tenant(company), authenticate(authorization)
        with company_transaction(dsn, company) as conn:
            state = session_row(conn, company, hashed)
            if state["phase"] != "consent":
                raise HTTPException(409, "A scoped quotation request is required.")
            if data.consent:
                conn.execute("""
                    UPDATE conversations SET phase='contact', consented_at=now()
                    WHERE company_id=%s AND token_hash=%s
                """, (company, hashed))
                return reply(say("contact", state["language"]), state["language"], "quote", next_action="contact")
            clear_quote(conn, company, hashed)
        return reply(say("cancelled", state["language"]), state["language"], "quote_cancelled")

    @app.post("/api/{company}/quote/contact")
    def contact(company: str, data: QuoteContact, authorization: Auth = None):
        company, hashed = tenant(company), authenticate(authorization)
        if not acceptable_contact(data):
            raise HTTPException(422, "Enter a valid phone number or Telegram username.")
        reference = uuid4()
        with company_transaction(dsn, company) as conn:
            state = session_row(conn, company, hashed)
            if state["phase"] != "contact" or not state["consented_at"]:
                raise HTTPException(409, "Consent is required.")
            conn.execute("""
                INSERT INTO leads (company_id, id, business_type, modules, name, channel, contact, consented_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """, (company, reference, state["business_type"], state["modules"], data.name,
                  data.channel, data.contact, state["consented_at"]))
            clear_quote(conn, company, hashed)
        return reply(say("saved", state["language"], reference=str(reference)), state["language"],
                     "lead_saved", reference=str(reference))

    @app.post("/api/{company}/quote/cancel")
    def cancel(company: str, authorization: Auth = None):
        company, hashed = tenant(company), authenticate(authorization)
        with company_transaction(dsn, company) as conn:
            state = session_row(conn, company, hashed)
            clear_quote(conn, company, hashed)
        return reply(say("cancelled", state["language"]), state["language"], "quote_cancelled")

    static = Path(__file__).with_name("static")
    app.mount("/assets", StaticFiles(directory=static), name="assets")

    @app.get("/", include_in_schema=False)
    def home():
        return FileResponse(static / "index.html")

    return app


def configured_embeddings() -> Embeddings | None:
    url = os.environ.get("COMPANY_AI_EMBEDDINGS_URL", "")
    if not url:
        return None
    model = os.environ.get("COMPANY_AI_EMBEDDINGS_MODEL", "").strip()
    if not model:
        raise RuntimeError("Set COMPANY_AI_EMBEDDINGS_MODEL when configuring embeddings.")
    return Embeddings(url, model, os.environ.get("COMPANY_AI_EMBEDDINGS_KEY", ""))


def app_from_env() -> FastAPI:
    return create_app(
        os.environ["COMPANY_AI_DATABASE_URL"], fixed_company=os.environ.get("COMPANY_AI_SITE_COMPANY", ""),
        demo=os.environ.get("COMPANY_AI_DEMO") == "1", embeddings=configured_embeddings(),
        log_gap_text=os.environ.get("COMPANY_AI_LOG_GAP_TEXT") == "1",
    )
