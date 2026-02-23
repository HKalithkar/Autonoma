from __future__ import annotations

import json
import logging
import os
from logging.handlers import SysLogHandler
from typing import Any

import httpx

_LOGGER = logging.getLogger("autonoma.audit.forwarder")


class ForwarderSettings:
    def __init__(self) -> None:
        self.syslog_enabled = os.getenv("AUDIT_FORWARD_SYSLOG", "false").lower() == "true"
        self.syslog_host = os.getenv("AUDIT_SYSLOG_HOST", "localhost")
        self.syslog_port = int(os.getenv("AUDIT_SYSLOG_PORT", "514"))
        self.syslog_protocol = os.getenv("AUDIT_SYSLOG_PROTOCOL", "udp").lower()
        self.http_url = os.getenv("AUDIT_FORWARD_HTTP_URL", "").strip()
        self.http_headers = os.getenv("AUDIT_FORWARD_HTTP_HEADERS", "{}")
        self.http_timeout = float(os.getenv("AUDIT_FORWARD_HTTP_TIMEOUT", "3.0"))


def _parse_headers(raw: str) -> dict[str, str]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if isinstance(data, dict):
        return {str(k): str(v) for k, v in data.items()}
    return {}


def forward_audit_event(payload: dict[str, Any]) -> None:
    settings = ForwarderSettings()
    serialized = json.dumps(payload, sort_keys=True)

    if settings.syslog_enabled:
        try:
            if settings.syslog_protocol == "tcp":
                handler = SysLogHandler(
                    address=(settings.syslog_host, settings.syslog_port), socktype=None
                )
            else:
                handler = SysLogHandler(address=(settings.syslog_host, settings.syslog_port))
            handler.emit(logging.makeLogRecord({"msg": serialized}))
            handler.close()
        except Exception:  # noqa: BLE001
            _LOGGER.warning("syslog forward failed", exc_info=True)

    if settings.http_url:
        headers = _parse_headers(settings.http_headers)
        try:
            httpx.post(
                settings.http_url, json=payload, headers=headers, timeout=settings.http_timeout
            )
        except Exception:  # noqa: BLE001
            _LOGGER.warning("http forward failed", exc_info=True)
