import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.vector_store import (  # noqa: E402
    HashEmbeddingProvider,
    QdrantVectorStore,
    VectorRecord,
    WeaviateVectorStore,
)


class _Response:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("http error")


def test_hash_embedder_dim() -> None:
    provider = HashEmbeddingProvider()
    vectors = provider.embed(["hello", "world"])
    assert len(vectors) == 2
    assert len(vectors[0]) == provider.dim


def test_weaviate_upsert_creates_schema(monkeypatch) -> None:
    calls = {"get": 0, "post": 0}

    def fake_get(*args, **kwargs):
        calls["get"] += 1
        return _Response(status_code=404)

    def fake_post(*args, **kwargs):
        calls["post"] += 1
        return _Response(status_code=200)

    monkeypatch.setattr("app.vector_store.httpx.get", fake_get)
    monkeypatch.setattr("app.vector_store.httpx.post", fake_post)

    store = WeaviateVectorStore("http://weaviate", "AutonomaMemory", HashEmbeddingProvider())
    ids = store.upsert_texts(
        "default",
        [VectorRecord(id="1", text="doc", metadata={"type": "document"})],
    )
    assert ids == ["1"]
    assert calls["post"] >= 2


def test_qdrant_upsert_creates_collection(monkeypatch) -> None:
    calls = {"get": 0, "put": 0}

    def fake_get(*args, **kwargs):
        calls["get"] += 1
        return _Response(status_code=404)

    def fake_put(*args, **kwargs):
        calls["put"] += 1
        return _Response(status_code=200)

    monkeypatch.setattr("app.vector_store.httpx.get", fake_get)
    monkeypatch.setattr("app.vector_store.httpx.put", fake_put)

    store = QdrantVectorStore("http://qdrant", "autonoma_memory", HashEmbeddingProvider())
    ids = store.upsert_texts(
        "default",
        [VectorRecord(id="1", text="doc", metadata={"type": "document"})],
    )
    assert ids == ["1"]
    assert calls["put"] >= 2
