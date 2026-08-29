import re
from typing import Any

# Regex patterns for common sensitive identifiers
_EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
)
_CREDIT_CARD_PATTERN = re.compile(
    r"\b(?:\d{4}[ -]?){3}\d{4}\b"
)
_PHONE_PATTERN = re.compile(
    r"(?:\+?\d{1,3}[ -]?)?\(?\d{3}\)?[ -]?\d{3}[ -]?\d{4}\b|(?:\+84|0)(?:3|5|7|8|9)\d{8}\b"
)
_SSN_PATTERN = re.compile(
    r"\b\d{3}-\d{2}-\d{4}\b"
)
_IP_PATTERN = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b"
)


def redact_text(text: str) -> str:
    """Redact sensitive PII patterns from free text before entering LLM context."""
    if not text:
        return text

    redacted = _EMAIL_PATTERN.sub("[EMAIL_REDACTED]", text)
    redacted = _CREDIT_CARD_PATTERN.sub("[CARD_REDACTED]", redacted)
    redacted = _PHONE_PATTERN.sub("[PHONE_REDACTED]", redacted)
    redacted = _SSN_PATTERN.sub("[SSN_REDACTED]", redacted)
    redacted = _IP_PATTERN.sub("[IP_REDACTED]", redacted)
    return redacted


def redact_sample_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Redact PII values from sample rows extracted by Data Inspector."""
    redacted_rows: list[dict[str, Any]] = []
    for row in rows:
        redacted_row: dict[str, Any] = {}
        for key, value in row.items():
            if isinstance(value, str):
                redacted_row[key] = redact_text(value)
            else:
                redacted_row[key] = value
        redacted_rows.append(redacted_row)
    return redacted_rows
