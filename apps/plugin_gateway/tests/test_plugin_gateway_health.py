import httpx
from fastapi.testclient import TestClient

from apps.plugin_gateway.app import main

app = main.app


def test_healthz() -> None:
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"


def test_readyz(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    async def fake_request_with_retry(method: str, url: str, **kwargs):
        calls.append((method, url))
        return object()

    monkeypatch.setattr(main, "_request_with_retry", fake_request_with_retry)
    client = TestClient(app)
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    assert calls == [
        ("GET", "http://policy:8181/health"),
        ("GET", "http://api:8000/healthz"),
    ]


def test_readyz_fails_when_dependency_unavailable(monkeypatch) -> None:
    async def fake_request_with_retry(method: str, url: str, **kwargs):
        if "policy:8181" in url:
            request = httpx.Request(method, url)
            raise httpx.ConnectError("unavailable", request=request)
        return object()

    monkeypatch.setattr(main, "_request_with_retry", fake_request_with_retry)
    client = TestClient(app)
    response = client.get("/readyz")
    assert response.status_code == 503
    payload = response.json()
    assert payload["detail"]["status"] == "not_ready"
    assert payload["detail"]["dependencies"]["policy"] == "unreachable"
