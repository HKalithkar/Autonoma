from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class VectorRecord:
    id: str
    text: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class VectorSearchResult:
    id: str
    score: float
    text: str
    metadata: dict[str, Any]


class VectorStoreError(RuntimeError):
    pass


class EmbeddingProvider:
    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class HashEmbeddingProvider(EmbeddingProvider):
    def __init__(self, dim: int = 64) -> None:
        self._dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            digest = _hash_bytes(text)
            values = [b / 255.0 for b in digest]
            while len(values) < self._dim:
                values.extend(values)
            vectors.append(values[: self._dim])
        return vectors

    @property
    def dim(self) -> int:
        return self._dim


class VectorStore:
    def upsert_texts(self, tenant_id: str, records: list[VectorRecord]) -> list[str]:
        raise NotImplementedError

    def query(
        self,
        tenant_id: str,
        text: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        raise NotImplementedError


class NullVectorStore(VectorStore):
    def upsert_texts(self, tenant_id: str, records: list[VectorRecord]) -> list[str]:
        return [record.id for record in records]

    def query(
        self,
        tenant_id: str,
        text: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        return []


class WeaviateVectorStore(VectorStore):
    def __init__(self, base_url: str, collection: str, embedder: EmbeddingProvider) -> None:
        self._base_url = base_url.rstrip("/")
        self._collection = collection
        self._embedder = embedder
        self._schema_ready = False

    def upsert_texts(self, tenant_id: str, records: list[VectorRecord]) -> list[str]:
        if not records:
            return []
        self._ensure_schema()
        vectors = self._embedder.embed([record.text for record in records])
        for record, vector in zip(records, vectors):
            payload = {
                "class": self._collection,
                "id": record.id,
                "properties": {
                    "tenant_id": tenant_id,
                    "text": record.text,
                    "type": record.metadata.get("type"),
                    "source": record.metadata.get("source"),
                    "correlation_id": record.metadata.get("correlation_id"),
                    "agent_type": record.metadata.get("agent_type"),
                },
                "vector": vector,
            }
            response = httpx.post(f"{self._base_url}/v1/objects", json=payload, timeout=5.0)
            response.raise_for_status()
        return [record.id for record in records]

    def query(
        self,
        tenant_id: str,
        text: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        self._ensure_schema()
        vector = self._embedder.embed([text])[0]
        where_clause = _build_weaviate_where(tenant_id, filters or {})
        query = {
            "query": (
                f"{{Get{{{self._collection}(nearVector:{{vector:{vector}}} "
                f"limit:{top_k} {where_clause}){{text type source correlation_id agent_type "
                f"_additional{{id distance}}}}}}}}"
            )
        }
        response = httpx.post(f"{self._base_url}/v1/graphql", json=query, timeout=5.0)
        response.raise_for_status()
        data = response.json()
        results = data.get("data", {}).get("Get", {}).get(self._collection, [])
        output: list[VectorSearchResult] = []
        for item in results:
            additional = item.get("_additional", {})
            output.append(
                VectorSearchResult(
                    id=additional.get("id", ""),
                    score=float(additional.get("distance", 0.0)),
                    text=item.get("text", ""),
                    metadata={
                        "type": item.get("type"),
                        "source": item.get("source"),
                        "correlation_id": item.get("correlation_id"),
                        "agent_type": item.get("agent_type"),
                    },
                )
            )
        return output

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        response = httpx.get(f"{self._base_url}/v1/schema/{self._collection}", timeout=5.0)
        if response.status_code == 200:
            self._schema_ready = True
            return
        if response.status_code != 404:
            raise VectorStoreError("weaviate_schema_check_failed")
        schema_payload = {
            "class": self._collection,
            "vectorizer": "none",
            "properties": [
                {"name": "tenant_id", "dataType": ["text"]},
                {"name": "text", "dataType": ["text"]},
                {"name": "type", "dataType": ["text"]},
                {"name": "source", "dataType": ["text"]},
                {"name": "correlation_id", "dataType": ["text"]},
                {"name": "agent_type", "dataType": ["text"]},
            ],
        }
        create_resp = httpx.post(f"{self._base_url}/v1/schema", json=schema_payload, timeout=5.0)
        create_resp.raise_for_status()
        self._schema_ready = True


class QdrantVectorStore(VectorStore):
    def __init__(self, base_url: str, collection: str, embedder: EmbeddingProvider) -> None:
        self._base_url = base_url.rstrip("/")
        self._collection = collection
        self._embedder = embedder
        self._collection_ready = False

    def upsert_texts(self, tenant_id: str, records: list[VectorRecord]) -> list[str]:
        if not records:
            return []
        self._ensure_collection()
        vectors = self._embedder.embed([record.text for record in records])
        points = []
        for record, vector in zip(records, vectors):
            payload = {
                "tenant_id": tenant_id,
                "text": record.text,
            }
            payload.update(record.metadata)
            points.append(
                {
                    "id": record.id,
                    "vector": vector,
                    "payload": payload,
                }
            )
        response = httpx.put(
            f"{self._base_url}/collections/{self._collection}/points?wait=true",
            json={"points": points},
            timeout=5.0,
        )
        response.raise_for_status()
        return [record.id for record in records]

    def query(
        self,
        tenant_id: str,
        text: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        self._ensure_collection()
        vector = self._embedder.embed([text])[0]
        payload = {
            "vector": vector,
            "limit": top_k,
            "with_payload": True,
            "filter": _build_qdrant_filter(tenant_id, filters or {}),
        }
        response = httpx.post(
            f"{self._base_url}/collections/{self._collection}/points/search",
            json=payload,
            timeout=5.0,
        )
        response.raise_for_status()
        data = response.json()
        output: list[VectorSearchResult] = []
        for item in data.get("result", []):
            payload = item.get("payload", {}) or {}
            output.append(
                VectorSearchResult(
                    id=str(item.get("id", "")),
                    score=float(item.get("score", 0.0)),
                    text=str(payload.get("text", "")),
                    metadata={k: payload.get(k) for k in payload if k != "text"},
                )
            )
        return output

    def _ensure_collection(self) -> None:
        if self._collection_ready:
            return
        response = httpx.get(f"{self._base_url}/collections/{self._collection}", timeout=5.0)
        if response.status_code == 200:
            self._collection_ready = True
            return
        if response.status_code != 404:
            raise VectorStoreError("qdrant_collection_check_failed")
        dim = self._embedder.dim if isinstance(self._embedder, HashEmbeddingProvider) else 64
        payload = {
            "vectors": {"size": dim, "distance": "Cosine"},
        }
        create_resp = httpx.put(
            f"{self._base_url}/collections/{self._collection}",
            json=payload,
            timeout=5.0,
        )
        create_resp.raise_for_status()
        self._collection_ready = True


_VECTOR_STORE_CACHE: dict[tuple[str, str, str, str, str], VectorStore] = {}


def get_vector_store() -> VectorStore:
    provider = os.getenv("VECTOR_STORE_PROVIDER", "weaviate").lower()
    collection = os.getenv("VECTOR_COLLECTION", "autonoma_memory")
    embedding_provider = os.getenv("EMBEDDING_PROVIDER", "hash").lower()
    cache_key = (
        provider,
        collection,
        os.getenv("WEAVIATE_URL", "http://weaviate:8080"),
        os.getenv("QDRANT_URL", "http://qdrant:6333"),
        embedding_provider,
    )
    if cache_key in _VECTOR_STORE_CACHE:
        return _VECTOR_STORE_CACHE[cache_key]
    embedder = _get_embedder(embedding_provider)
    if provider == "disabled":
        store: VectorStore = NullVectorStore()
        _VECTOR_STORE_CACHE[cache_key] = store
        return store
    if provider == "qdrant":
        base_url = os.getenv("QDRANT_URL", "http://qdrant:6333")
        store = QdrantVectorStore(base_url, collection, embedder)
        _VECTOR_STORE_CACHE[cache_key] = store
        return store
    base_url = os.getenv("WEAVIATE_URL", "http://weaviate:8080")
    store = WeaviateVectorStore(base_url, collection, embedder)
    _VECTOR_STORE_CACHE[cache_key] = store
    return store


def _get_embedder(provider: str | None = None) -> EmbeddingProvider:
    raw_provider = provider if provider is not None else os.getenv("EMBEDDING_PROVIDER", "hash")
    provider_name = str(raw_provider).lower()
    if provider_name == "hash":
        return HashEmbeddingProvider()
    raise VectorStoreError(f"unsupported_embedder:{provider_name}")


def _hash_bytes(text: str) -> bytes:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).digest()


def build_records(
    *,
    tenant_id: str,
    texts: list[str],
    metadata: dict[str, Any],
) -> list[VectorRecord]:
    records = []
    for text in texts:
        records.append(
            VectorRecord(
                id=str(uuid.uuid4()),
                text=text,
                metadata={**metadata, "tenant_id": tenant_id},
            )
        )
    return records


def _build_weaviate_where(tenant_id: str, filters: dict[str, Any]) -> str:
    operands = [f'{{path:["tenant_id"],operator:Equal,valueText:"{tenant_id}"}}']
    for key, value in filters.items():
        if value is None or value == "":
            continue
        operands.append(f'{{path:["{key}"],operator:Equal,valueText:"{value}"}}')
    if len(operands) == 1:
        return f"where:{operands[0]}"
    joined = ",".join(operands)
    return f"where:{{operator:And,operands:[{joined}]}}"


def _build_qdrant_filter(tenant_id: str, filters: dict[str, Any]) -> dict[str, Any]:
    must = [{"key": "tenant_id", "match": {"value": tenant_id}}]
    for key, value in filters.items():
        if value is None or value == "":
            continue
        must.append({"key": key, "match": {"value": value}})
    return {"must": must}
