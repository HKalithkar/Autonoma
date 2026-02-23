import sys
from pathlib import Path

from fastapi.testclient import TestClient

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.main import app  # noqa: E402


def test_memory_ingest_requires_token(monkeypatch) -> None:
    monkeypatch.setenv("SERVICE_TOKEN", "token")
    client = TestClient(app)
    response = client.post(
        "/v1/memory/ingest",
        json={"texts": ["failure"], "metadata": {}, "context": {"tenant_id": "default"}},
    )
    assert response.status_code == 401


def test_memory_ingest_accepts_token(monkeypatch) -> None:
    monkeypatch.setenv("SERVICE_TOKEN", "token")

    class _FakeStore:
        def upsert_texts(self, tenant_id, records):
            return [record.id for record in records]

    monkeypatch.setattr("app.main.get_vector_store", lambda: _FakeStore())
    client = TestClient(app)
    response = client.post(
        "/v1/memory/ingest",
        headers={"x-service-token": "token"},
        json={
            "texts": ["failure"],
            "metadata": {"type": "failure"},
            "context": {"tenant_id": "default"},
        },
    )
    assert response.status_code == 200


def test_memory_search_requires_token(monkeypatch) -> None:
    monkeypatch.setenv("SERVICE_TOKEN", "token")
    client = TestClient(app)
    response = client.post(
        "/v1/memory/search",
        json={"query": "failure", "context": {"tenant_id": "default"}},
    )
    assert response.status_code == 401


def test_memory_search_accepts_token(monkeypatch) -> None:
    monkeypatch.setenv("SERVICE_TOKEN", "token")

    class _FakeStore:
        def query(self, tenant_id, text, top_k=5, filters=None):
            return []

    monkeypatch.setattr("app.main.get_vector_store", lambda: _FakeStore())
    client = TestClient(app)
    response = client.post(
        "/v1/memory/search",
        headers={"x-service-token": "token"},
        json={"query": "failure", "context": {"tenant_id": "default"}},
    )
    assert response.status_code == 200
