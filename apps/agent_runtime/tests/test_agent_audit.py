import os
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.audit import build_llm_audit_event, emit_audit_events  # noqa: E402
from app.llm import LLMConfig, _AuditedChatModel  # noqa: E402


class _FakeInner:
    def __init__(self, content: str) -> None:
        self._content = content

    def invoke(self, messages):
        class _Resp:
            def __init__(self, content: str) -> None:
                self.content = content

        return _Resp(self._content)


def test_build_llm_audit_event_redacts() -> None:
    event = build_llm_audit_event(
        agent_type="orchestrator",
        correlation_id="c1",
        actor_id="a1",
        tenant_id="t1",
        model="test-model",
        api_url="http://llm",
        prompt="hello",
        response="world",
        latency_ms=12.5,
        status="ok",
    )
    details = event["details"]
    assert "prompt_hash" in details
    assert "response_hash" in details
    assert details["prompt_chars"] == 5
    assert details["response_chars"] == 5
    assert "hello" not in str(details)
    assert "world" not in str(details)


def test_audited_chat_emits_event(monkeypatch) -> None:
    os.environ["AUDIT_INGEST_TOKEN"] = "token"
    emitted = []

    def fake_emit(events):
        emitted.extend(events)

    monkeypatch.setattr("app.llm.emit_audit_events", fake_emit)
    model = _AuditedChatModel(
        _FakeInner("ok"),
        config=LLMConfig(
            agent_type="orchestrator",
            api_url="http://llm",
            model="model-1",
            api_key_ref="env:LLM_API_KEY",
        ),
        correlation_id="c2",
        actor_id="a2",
        tenant_id="t2",
    )
    model.invoke([{"type": "human", "content": "hello"}])
    assert emitted
    assert emitted[0]["event_type"] == "llm.call"


def test_emit_audit_events_no_token(monkeypatch) -> None:
    os.environ.pop("AUDIT_INGEST_TOKEN", None)
    called = False

    def fake_post(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr("app.audit.httpx.post", fake_post)
    emit_audit_events([])
    assert called is False
