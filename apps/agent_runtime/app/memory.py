from __future__ import annotations

import json
import os
from typing import Any, cast

from pydantic import BaseModel

redis: Any | None
try:
    import redis as redis_module  # type: ignore
except ImportError:  # pragma: no cover - fallback for tests
    redis = None
else:
    redis = redis_module


class MemoryRef(BaseModel):
    ref_type: str
    ref_uri: str
    metadata: dict[str, Any]


class MemoryStore:
    def store_short_term(self, key: str, payload: dict[str, Any]) -> None:
        raise NotImplementedError

    def store_long_term(self, tenant_id: str, refs: list[MemoryRef]) -> None:
        raise NotImplementedError

    def get_short_term(self, key: str) -> dict[str, Any] | None:
        raise NotImplementedError


class LocalMemoryStore(MemoryStore):
    def __init__(self) -> None:
        self._short_term: dict[str, dict[str, Any]] = {}
        self._long_term: dict[str, list[dict[str, Any]]] = {}

    def store_short_term(self, key: str, payload: dict[str, Any]) -> None:
        self._short_term[key] = payload

    def store_long_term(self, tenant_id: str, refs: list[MemoryRef]) -> None:
        records = self._long_term.setdefault(tenant_id, [])
        for ref in refs:
            records.append(
                {"ref_type": ref.ref_type, "ref_uri": ref.ref_uri, "metadata": ref.metadata}
            )

    def get_short_term(self, key: str) -> dict[str, Any] | None:
        return self._short_term.get(key)


class RedisMemoryStore(MemoryStore):
    def __init__(self, redis_url: str) -> None:
        if redis is None:
            raise RuntimeError("redis package not available")
        self._client = redis.Redis.from_url(redis_url, decode_responses=True)

    def store_short_term(self, key: str, payload: dict[str, Any]) -> None:
        self._client.set(f"memory:short:{key}", json.dumps(payload), ex=3600)

    def store_long_term(self, tenant_id: str, refs: list[MemoryRef]) -> None:
        key = f"memory:long:{tenant_id}"
        for ref in refs:
            self._client.rpush(
                key,
                json.dumps(
                    {"ref_type": ref.ref_type, "ref_uri": ref.ref_uri, "metadata": ref.metadata}
                ),
            )

    def get_short_term(self, key: str) -> dict[str, Any] | None:
        value = self._client.get(f"memory:short:{key}")
        if value is None:
            return None
        return json.loads(cast(str, value))


_MEMORY_STORE: MemoryStore | None = None


def get_memory_store() -> MemoryStore:
    global _MEMORY_STORE
    if _MEMORY_STORE is not None:
        return _MEMORY_STORE
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    if redis_url and redis is not None:
        try:
            candidate = RedisMemoryStore(redis_url)
            candidate._client.ping()
            _MEMORY_STORE = candidate
        except Exception:
            _MEMORY_STORE = LocalMemoryStore()
    else:
        _MEMORY_STORE = LocalMemoryStore()
    return _MEMORY_STORE
