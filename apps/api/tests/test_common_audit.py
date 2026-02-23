from __future__ import annotations

import json

from libs.common import audit as audit_module
from libs.common.context import set_request_context


def test_audit_event_redacts_and_describes(monkeypatch, caplog) -> None:
    class DummyCounter:
        def __init__(self) -> None:
            self.count = 0

        def labels(self, **kwargs):  # noqa: ANN003
            return self

        def inc(self) -> None:
            self.count += 1

    monkeypatch.setattr(audit_module, "AUDIT_EVENTS", DummyCounter())
    set_request_context("corr-1", "user-1", "default")

    with caplog.at_level("INFO", logger="autonoma.audit"):
        audit_module.audit_event(
            "authz",
            "allow",
            {"permission": "workflow:read", "token": "secret"},
        )

    assert caplog.records
    payload = json.loads(caplog.records[0].message)
    assert payload["details"]["token"] == "[REDACTED]"
    assert "description" in payload["details"]
