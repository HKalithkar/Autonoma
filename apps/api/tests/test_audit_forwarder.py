from __future__ import annotations

import os
from typing import Any

from apps.api.app.audit_forwarder import _parse_headers, forward_audit_event


def test_parse_headers() -> None:
    assert _parse_headers('{"X-Test":"1"}') == {"X-Test": "1"}
    assert _parse_headers('["nope"]') == {}
    assert _parse_headers("invalid") == {}


def test_forward_audit_event_http(monkeypatch) -> None:
    os.environ["AUDIT_FORWARD_SYSLOG"] = "false"
    os.environ["AUDIT_FORWARD_HTTP_URL"] = "http://example"
    os.environ["AUDIT_FORWARD_HTTP_HEADERS"] = '{"X-Test":"1"}'
    os.environ["AUDIT_FORWARD_HTTP_TIMEOUT"] = "1.0"
    calls: list[dict[str, Any]] = []

    def fake_post(url: str, **kwargs: Any):
        calls.append({"url": url, "headers": kwargs.get("headers"), "json": kwargs.get("json")})

    monkeypatch.setattr("apps.api.app.audit_forwarder.httpx.post", fake_post)

    forward_audit_event({"event": "test"})
    assert calls[0]["url"] == "http://example"
    assert calls[0]["headers"] == {"X-Test": "1"}
    assert calls[0]["json"] == {"event": "test"}


def test_forward_audit_event_syslog(monkeypatch) -> None:
    os.environ["AUDIT_FORWARD_SYSLOG"] = "true"
    os.environ["AUDIT_SYSLOG_PROTOCOL"] = "udp"
    os.environ["AUDIT_FORWARD_HTTP_URL"] = ""

    emitted: list[str] = []

    class FakeSysLogHandler:
        def __init__(self, address, socktype=None):  # noqa: D401, ANN001
            self.address = address

        def emit(self, record) -> None:  # noqa: ANN001
            emitted.append(record.msg)

        def close(self) -> None:
            return None

    monkeypatch.setattr("apps.api.app.audit_forwarder.SysLogHandler", FakeSysLogHandler)

    forward_audit_event({"event": "syslog"})
    assert emitted
