import sys
from pathlib import Path

from fastapi.testclient import TestClient

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

import app.main as main_module  # noqa: E402
from app.llm import LLMResolutionError  # noqa: E402
from app.main import app  # noqa: E402


def test_healthz(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "llm" in payload


def test_readyz(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    main_module._LLM_READY["status"] = "unknown"
    main_module._LLM_READY["detail"] = "startup"
    main_module._LLM_READY["checked_at"] = "0"
    client = TestClient(app)
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readyz_recovers_after_transient_readiness_error(monkeypatch) -> None:
    client = TestClient(app)
    calls = {"count": 0}

    def _flaky_check() -> None:
        calls["count"] += 1
        if calls["count"] == 1:
            raise LLMResolutionError("secret_resolution_failed")

    monkeypatch.setattr(main_module, "_check_llm_readiness", _flaky_check)
    monkeypatch.setenv("LLM_READINESS_RECHECK_SECONDS", "0")
    main_module._LLM_READY["status"] = "error"
    main_module._LLM_READY["detail"] = "secret_resolution_failed"
    main_module._LLM_READY["checked_at"] = "0"

    first = client.get("/readyz")
    assert first.status_code == 503
    second = client.get("/readyz")
    assert second.status_code == 200
    assert second.json() == {"status": "ready"}
