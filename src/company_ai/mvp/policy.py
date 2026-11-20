"""Bilingual routing rules applied before retrieval and before displaying evidence."""

import re
import unicodedata

from company_ai.data.ingestion import COMPANIES
from company_ai.data.normalization import language_tag, normalize

QUOTE = re.compile(
    r"\b(?:pric\w*|cost\w*|quot\w*|fee\w*|charg\w*|budget\w*|"
    r"rate\w*|discount\w*|cheapest|afford\w*|how\s+much|ballpark|"
    r"tam\s?lai|tamlai|ponman|bonman)\b|តម្លៃ|ប៉ុន្មាន|ថ្លៃ|ចំណាយ|សម្រង់តម្លៃ",
    re.IGNORECASE,
)
HOW_TO = re.compile(
    r"\b(?:how\s+(?:do|can|to|should|would)\b|step[ -]by[ -]step|steps?\b|"
    r"where\s+(?:do|can|is)\b|(?:show|tell)\s+me\s+how|"
    r"configure|troubleshoot|click|set\s*up|install)\b|របៀប|ដូចម្តេច|ចុច|ជំហាន|ដំឡើង|កំណត់រចនាសម្ព័ន្ធ",
    re.IGNORECASE,
)
PROCEDURE_DETAIL = re.compile(
    r"\b(?:steps?|click|buttons?|menus?|configure|troubleshoot|install|set\s+up)\b"
    r"|ចុច|ជំហាន|ដំឡើង|កំណត់រចនាសម្ព័ន្ធ",
    re.IGNORECASE,
)
FAQ_HOW_TO = re.compile(
    r"\breport(?:ing)?\s+(?:(?:a|an|the|this|my)\s+)?(?:issue|problem|bug)\b"
    r"|\bhow\s+(?:can|is)\s+(?:the\s+)?(?:software|system|application|it|maqsu(?:\s+accounting)?)\s+(?:be\s+)?deployed\b"
    r"|រាយការណ៍.{0,70}បញ្ហា|បញ្ហា.{0,70}រាយការណ៍",
    re.IGNORECASE,
)
MONEY = re.compile(
    r"[$€£៛]|\b(?:USD|KHR|dollars?|riel)\b|ដុល្លារ|រៀល",
    re.IGNORECASE,
)
PRICE_EVIDENCE = re.compile(
    r"\b(?:pric\w*|cost\w*|fee\w*|quot\w*|discount\w*|"
    r"charge\w*|(?:per|a)\s+(?:month|year|user|seat))\b|តម្លៃ|ថ្លៃ|ចំណាយ",
    re.IGNORECASE,
)
CONTACT = re.compile(r"[\w.+-]+@[\w.-]+\.\w+|(?<!\w)@[\w_]+|\+?\d[\d ().-]{6,}\d")
CROSS_COMPANY = {
    company: re.compile(rf"(?<![a-z]){re.escape(company)}(?![a-z])", re.IGNORECASE)
    for company in COMPANIES
}


def intent_text(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text)
    return normalize("".join(char for char in folded if unicodedata.category(char) != "Cf"))


def requests_price(message: str) -> bool:
    message = intent_text(message)
    return bool(QUOTE.search(message) or MONEY.search(message))


def requires_procedure(message: str) -> bool:
    message = intent_text(message)
    return bool(HOW_TO.search(message) and (
        PROCEDURE_DETAIL.search(message) or not FAQ_HOW_TO.search(message)
    ))


def unsafe_evidence(value: str) -> bool:
    value = intent_text(value)
    return bool(MONEY.search(value) or (PRICE_EVIDENCE.search(value) and any(c.isdecimal() for c in value)))


def mentions_other_company(company: str, message: str) -> bool:
    return any(tag != company and pattern.search(intent_text(message)) for tag, pattern in CROSS_COMPANY.items())


def select_language(message: str, previous: str, explicit: str | None) -> str:
    if explicit is not None:
        return explicit
    tag = language_tag(message)
    if tag in {"km_script", "mixed_km_latin"}:
        return "km"
    return "en" if tag == "latin_script" else previous


def redact_contact(message: str) -> str:
    return CONTACT.sub("[redacted]", message)
