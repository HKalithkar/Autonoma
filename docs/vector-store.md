# Vector Store Architecture (Weaviate/Qdrant)

## Goals
- Provide a vendor-neutral abstraction so we can swap vector databases without rewrites.
- Support local dev with Docker/Kubernetes and production HA.
- Keep metadata and access controls aligned with Autonoma tenancy.

## Abstraction
The agent runtime uses a thin vector store interface:

- `upsert_texts(tenant_id, records)` — store text + metadata as embeddings.
- `query(tenant_id, text, top_k, filters)` — retrieval API used by UI search.

All vector store records use a common schema:
- `id` (uuid)
- `text` (raw content)
- `metadata` (json object):
  - `tenant_id`
  - `type` (document/plan/summary)
  - `source` (workflow/agent/runtime)
  - `correlation_id`
  - `agent_type`

No vendor-specific fields live in core business models. Provider-specific adapters translate
these fields into Weaviate properties or Qdrant payloads.

## Providers
### Weaviate (recommended for production knowledge systems)
- Strong schema support and metadata filtering.
- Clustered HA deployments supported.
- Heavier footprint than Qdrant.

### Qdrant (recommended for lightweight dev/ops)
- Simple cluster model and lighter resource use.
- Good performance for basic vector search.
- Fewer built-in schema features.

## Configuration
Environment variables:
- `VECTOR_STORE_PROVIDER`: `weaviate` | `qdrant` | `disabled`
- `VECTOR_COLLECTION`: shared collection/class name
- `WEAVIATE_URL`: base URL for Weaviate
- `QDRANT_URL`: base URL for Qdrant
- `EMBEDDING_PROVIDER`: `hash` (default). Production should use a real embedder.
- `MEMORY_SEARCH_TOP_K`: default top-K retrieval size for pre-plan search.

Note: only the `hash` embedder is implemented today. This keeps local dev fully
offline. For production, plug in a real embedding provider (local or managed)
behind the same interface.

## Retrieval API
The API exposes:
- `POST /v1/memory/search` (requires `memory:read`)

Request:
```json
{"query":"refresh cache","top_k":5,"filters":{"type":"plan"}}
```

Response:
```json
{"results":[{"id":"...","score":0.12,"text":"...","metadata":{"type":"plan"}}]}
```

The Web UI includes a **Memory search** panel that calls this endpoint.

## Pre-plan retrieval
Before planning, the Orchestrator queries the vector store using the goal text
and injects results into the plan prompt as *untrusted* context.

Failures from GitOps webhooks are also written to vector memory with
`type=failure`, allowing the planner to surface prior incident context.

## How to test
1) Trigger an agent run so plan text is stored in the vector store.
2) Open UI → **Memory search**.
3) Search for a keyword from the plan (e.g., "refresh caches").
4) Expect results with `type=plan` and `source=agent-runtime`.

We keep embeddings provider and vector DB separate so you can switch providers
without changing how embeddings are produced.

## Local Dev
Use the Docker service in `infra/docker-compose.yml`. Default class name is
`AutonomaMemory` (Weaviate requires CamelCase class names).
- Weaviate on `http://weaviate:8080`
- Qdrant on `http://qdrant:6333` (optional profile: `docker compose --profile qdrant up`)

## Production HA Guidance
Weaviate:
- Run 3+ nodes with replication enabled.
- Use a load balancer service endpoint.
- Regular backups and schema migration plan.

Qdrant:
- Run a multi-node cluster with replication factor > 1.
- Use a stable service endpoint.
- Regular backups and reindexing procedures.

## Migration (Qdrant ↔ Weaviate)
Because we store vendor-neutral `text` + `metadata`, the migration path is:
1. Export records from the source provider (id, text, metadata, vectors if needed).
2. Re-embed text if you are switching embedder settings.
3. Import records into the target provider via the adapter.

We will keep a migration script under `tools/` to automate this when we add retrieval.

## Security & Redaction
- Do not store secrets in vector content.
- Prefer redacted documents at the ingestion boundary.
- Always associate `tenant_id` and `correlation_id` metadata.
