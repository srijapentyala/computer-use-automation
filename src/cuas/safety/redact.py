"""Redact secrets and regulated financial identifiers from logs and artifacts."""

from __future__ import annotations

import re
from typing import Any

SENSITIVE_KEY = re.compile(
    r"(password|passwd|secret|token|authorization|ssn|social|routing|pin|account.?number)",
    re.I,
)

PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]"),
    (re.compile(r"\b\d{9}\b"), "[TAX_ID]"),
    (re.compile(r"\b(?:\d[ -]*?){13,16}\b"), "[PAN]"),
    (re.compile(r"\b(?:SV|CK|MM)-\d{4,}\b"), "[ACCOUNT]"),
    (re.compile(r"(?i)(password|passwd|pin|token)\s*[:=]\s*\S+"), r"\1=[REDACTED]"),
    (
        re.compile(r"(?i)authorization:\s*\S+"),
        "Authorization: [REDACTED]",
    ),
]


def redact_text(text: str | None) -> str:
    if not text:
        return ""
    out = text
    for pat, repl in PATTERNS:
        out = pat.sub(repl, out)
    return out


def is_sensitive_key(key: str) -> bool:
    return bool(SENSITIVE_KEY.search(key))


def redact_value(key: str, value: Any) -> Any:
    if is_sensitive_key(key):
        return "[REDACTED]"
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return redact_dict(value)
    if isinstance(value, list):
        return [redact_value(key, v) for v in value]
    return value


def redact_dict(data: dict[str, Any]) -> dict[str, Any]:
    return {k: redact_value(k, v) for k, v in data.items()}
