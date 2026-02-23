from __future__ import annotations

import asyncio
import sys
from types import ModuleType, SimpleNamespace

import pytest

from apps.runtime_orchestrator.app.event_bus import JetStreamPublisher


class _FakeJetStream:
    def __init__(self, *, subjects: list[str] | None, missing_stream: bool = False) -> None:
        self._subjects = subjects
        self._missing_stream = missing_stream
        self.add_calls: list[dict[str, object]] = []
        self.update_calls: list[dict[str, object]] = []
        self.publish_calls: list[tuple[str, bytes]] = []

    async def stream_info(self, _name: str) -> object:
        if self._missing_stream:
            raise RuntimeError("stream not found")
        return SimpleNamespace(config=SimpleNamespace(subjects=self._subjects))

    async def add_stream(self, *, name: str, subjects: list[str]) -> None:
        self.add_calls.append({"name": name, "subjects": subjects})

    async def update_stream(self, *, name: str, subjects: list[str]) -> None:
        self.update_calls.append({"name": name, "subjects": subjects})

    async def publish(self, subject: str, payload: bytes) -> None:
        self.publish_calls.append((subject, payload))


class _FakeNATSClient:
    def __init__(self, js: _FakeJetStream) -> None:
        self._js = js
        self.connected = False
        self.drained = False

    async def connect(self, *, servers: list[str], connect_timeout: int) -> None:
        self.connected = bool(servers) and connect_timeout > 0

    def jetstream(self) -> _FakeJetStream:
        return self._js

    async def drain(self) -> None:
        self.drained = True


def _install_fake_nats(monkeypatch: pytest.MonkeyPatch, js: _FakeJetStream) -> _FakeNATSClient:
    fake_client = _FakeNATSClient(js)

    def _client_factory() -> _FakeNATSClient:
        return fake_client

    nats_module = ModuleType("nats")
    nats_aio_module = ModuleType("nats.aio")
    nats_client_module = ModuleType("nats.aio.client")
    nats_client_module.Client = _client_factory  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "nats", nats_module)
    monkeypatch.setitem(sys.modules, "nats.aio", nats_aio_module)
    monkeypatch.setitem(sys.modules, "nats.aio.client", nats_client_module)
    return fake_client


def test_publish_creates_stream_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    js = _FakeJetStream(subjects=None, missing_stream=True)
    _install_fake_nats(monkeypatch, js)

    publisher = JetStreamPublisher(
        enabled=True,
        nats_url="nats://nats:4222",
        subject="runtime.events",
        stream_name="runtime_events",
    )
    asyncio.run(publisher._publish_async({"event_type": "run.created"}))

    assert js.add_calls == [{"name": "runtime_events", "subjects": ["runtime.events"]}]
    assert js.publish_calls


def test_publish_updates_stream_when_subject_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    js = _FakeJetStream(subjects=["runtime.other"])
    _install_fake_nats(monkeypatch, js)

    publisher = JetStreamPublisher(
        enabled=True,
        nats_url="nats://nats:4222",
        subject="runtime.events",
        stream_name="runtime_events",
    )
    asyncio.run(publisher._publish_async({"event_type": "run.created"}))

    assert js.update_calls == [
        {"name": "runtime_events", "subjects": ["runtime.other", "runtime.events"]}
    ]
    assert js.publish_calls


def test_publish_skips_stream_update_when_subject_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    js = _FakeJetStream(subjects=["runtime.events"])
    _install_fake_nats(monkeypatch, js)

    publisher = JetStreamPublisher(
        enabled=True,
        nats_url="nats://nats:4222",
        subject="runtime.events",
        stream_name="runtime_events",
    )
    asyncio.run(publisher._publish_async({"event_type": "run.created"}))

    assert js.update_calls == []
    assert js.add_calls == []
    assert js.publish_calls
