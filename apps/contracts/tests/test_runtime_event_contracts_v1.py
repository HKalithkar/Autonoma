from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

EVENT_SCHEMA_DIR = Path(__file__).resolve().parents[3] / "docs" / "contracts" / "events"


def _load_schema(filename: str) -> dict:
    path = EVENT_SCHEMA_DIR / filename
    return json.loads(path.read_text(encoding="utf-8"))


def _validator(filename: str) -> Draft202012Validator:
    schema = _load_schema(filename)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _base_event(event_type: str) -> dict:
    return {
        "event_id": "evt-1",
        "event_type": event_type,
        "schema_version": "v1",
        "run_id": "run-1",
        "step_id": "step-1",
        "timestamp": "2026-02-01T12:00:00Z",
        "correlation_id": "11111111-1111-1111-1111-111111111111",
        "actor_id": "user-1",
        "tenant_id": "tenant-a",
        "agent_id": "orchestrator_worker",
        "payload": {"message": "ok"},
        "visibility_level": "tenant",
        "redaction": "none",
    }


EVENT_SCHEMAS = [
    ("run.started.schema.json", "run.started"),
    ("plan.step.proposed.schema.json", "plan.step.proposed"),
    ("agent.message.sent.schema.json", "agent.message.sent"),
    ("policy.decision.recorded.schema.json", "policy.decision.recorded"),
    ("approval.requested.schema.json", "approval.requested"),
    ("approval.resolved.schema.json", "approval.resolved"),
    ("tool.call.started.schema.json", "tool.call.started"),
    ("tool.call.retrying.schema.json", "tool.call.retrying"),
    ("tool.call.completed.schema.json", "tool.call.completed"),
    ("tool.call.failed.schema.json", "tool.call.failed"),
    ("run.succeeded.schema.json", "run.succeeded"),
    ("run.failed.schema.json", "run.failed"),
    ("run.aborted.schema.json", "run.aborted"),
]


@pytest.mark.parametrize("schema_filename,event_type", EVENT_SCHEMAS)
def test_runtime_event_schema_accepts_valid_payload(schema_filename: str, event_type: str) -> None:
    _validator(schema_filename).validate(_base_event(event_type))


@pytest.mark.parametrize("schema_filename,event_type", EVENT_SCHEMAS)
def test_runtime_event_schema_rejects_missing_correlation(
    schema_filename: str,
    event_type: str,
) -> None:
    payload = _base_event(event_type)
    payload.pop("correlation_id")
    with pytest.raises(ValidationError):
        _validator(schema_filename).validate(payload)


@pytest.mark.parametrize("schema_filename,event_type", EVENT_SCHEMAS)
def test_runtime_event_schema_rejects_missing_actor(schema_filename: str, event_type: str) -> None:
    payload = _base_event(event_type)
    payload.pop("actor_id")
    with pytest.raises(ValidationError):
        _validator(schema_filename).validate(payload)


@pytest.mark.parametrize("schema_filename,event_type", EVENT_SCHEMAS)
def test_runtime_event_schema_rejects_missing_tenant(schema_filename: str, event_type: str) -> None:
    payload = _base_event(event_type)
    payload.pop("tenant_id")
    with pytest.raises(ValidationError):
        _validator(schema_filename).validate(payload)
