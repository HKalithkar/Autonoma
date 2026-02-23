from __future__ import annotations

import hashlib
import os
import re
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Span

_TRACER = trace.get_tracer("autonoma.agent_runtime")
_DEFAULT_PREVIEW_CHARS = 240
_FULL_TRACE_ENV = "LLM_TRACE_FULL"

_REDACTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"secretkeyref:[^\s\"']+", re.IGNORECASE), "secretkeyref:[redacted]"),
    (
        re.compile(r"(?i)authorization\s*[:=]\s*bearer\s+[A-Za-z0-9._-]+"),
        "authorization: bearer [redacted]",
    ),
    (
        re.compile(r"(?i)\b(api_key|token|password|secret)\b\s*[:=]\s*[^\s,;]+"),
        r"\1=[redacted]",
    ),
    (re.compile(r"sk-[A-Za-z0-9]{16,}"), "sk-[redacted]"),
]


def get_tracer():
    return _TRACER


def _preview_limit() -> int:
    value = os.getenv("LLM_TRACE_PREVIEW_CHARS")
    if not value:
        return _DEFAULT_PREVIEW_CHARS
    try:
        return max(0, int(value))
    except ValueError:
        return _DEFAULT_PREVIEW_CHARS


def full_trace_enabled() -> bool:
    return os.getenv(_FULL_TRACE_ENV, "false").lower() == "true"


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def redact_preview(value: str, *, max_chars: int | None = None) -> tuple[str, bool, bool]:
    redacted = value or ""
    for pattern, replacement in _REDACTION_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    was_redacted = redacted != (value or "")
    limit = _preview_limit() if max_chars is None else max_chars
    truncated = False
    if limit >= 0 and len(redacted) > limit:
        redacted = redacted[:limit]
        truncated = True
    return redacted, was_redacted, truncated


def set_span_context(
    span: Span | None,
    *,
    correlation_id: str | None,
    actor_id: str | None,
    tenant_id: str | None,
) -> None:
    if not span or not span.is_recording():
        return
    if correlation_id:
        span.set_attribute("correlation_id", correlation_id)
    if actor_id:
        span.set_attribute("actor_id", actor_id)
    if tenant_id:
        span.set_attribute("tenant_id", tenant_id)


def set_span_attributes(span: Span | None, attributes: dict[str, Any]) -> None:
    if not span or not span.is_recording():
        return
    for key, value in attributes.items():
        if value is None:
            continue
        span.set_attribute(key, value)
