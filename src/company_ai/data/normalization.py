"""Conservative normalization: retain originals and never infer translations."""

import re
import unicodedata


def normalize(value: str) -> str:
    """NFC plus collapsed Unicode whitespace; retain case and punctuation."""
    return " ".join(unicodedata.normalize("NFC", value).split())


def language_tag(value: str) -> str:
    """Script-based coverage, not a claim of linguistic quality or translation."""
    khmer = any(
        "KHMER" in unicodedata.name(char, "") and unicodedata.category(char).startswith("L")
        for char in value
    )
    latin = any(
        "LATIN" in unicodedata.name(char, "") and unicodedata.category(char).startswith("L")
        for char in value
    )
    if khmer and latin:
        return "mixed_km_latin"
    if khmer:
        return "km_script"
    if latin:
        return "latin_script"
    return "unknown" if value.strip() else "empty"


def has_control_characters(value: str) -> bool:
    return any(unicodedata.category(char) == "Cc" and char not in "\t\r\n" for char in value)


def question_key(value: str) -> str:
    """Only for duplicate/conflict detection, never for altering source text."""
    return normalize(value).casefold()


def safe_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9_-]", "_", value.lower())
