# Production Handbook

This handbook describes how to deploy Autonoma in production with secure
defaults, HA where required, and end-to-end observability.

## 1) Architecture at a glance
Services:
- Web UI
- API (gateway)
- Agent runtime
- Plugin Gateway
- Policy (OPA)
- Keycloak (OIDC)
- Postgres (metadata + audit)
- Redis (short-term memory)
- Vector DB (Weaviate or Qdrant)
- Observability stack (OTEL collector, Prometheus, Grafana)

All external side effects flow through the Plugin Gateway and are audited.

## 2) Prerequisites
- Kubernetes (recommended) or containers with an orchestrator.
- TLS termination (Ingress + cert-manager or equivalent).
- Managed Postgres (HA) and Redis (HA) or self-hosted equivalents.
- Object storage for backups (S3/GCS/Azure Blob).
- A secrets manager (Vault, AWS Secrets Manager, GCP Secret Manager).

Kubernetes starter manifests live in `infra/k8s/`.

## 3) DNS and TLS
- Create DNS entries for:
  - Web UI (e.g. `autonoma.example.com`)
  - API (e.g. `api.autonoma.example.com`)
  - Keycloak (e.g. `auth.autonoma.example.com`)
- Terminate TLS at the ingress. Enforce HTTPS-only for API and Keycloak.
- Ensure internal service-to-service calls use mTLS where supported.

## 4) OIDC / Keycloak
- Configure a realm (e.g. `autonoma`) and clients for Web + API.
- Set allowed redirect URIs:
  - Web UI: `https://autonoma.example.com/*`
  - API callback: `https://api.autonoma.example.com/v1/auth/callback`
- Ensure `KC_HOSTNAME_STRICT=true` and `KC_HOSTNAME_STRICT_HTTPS=true`.
- Map roles to Autonoma roles (`viewer`, `operator`, `approver`, `admin`).

## 5) Data stores
Postgres:
- Required for workflows, runs, approvals, audit, chat history.
- Configure HA (primary + replicas) and backups.

Redis:
- Short-term agent memory/state.
- Configure persistence if needed for longer retention.

Vector DB:
- Weaviate (default) or Qdrant.
- Configure for HA and persistence.

## 6) Secrets and identity
- Do not store raw secrets in env files.
- Use secret references:
  - `env:VAR_NAME` for legacy env-based secrets.
  - `secretkeyref:plugin:<name>:<path>` for secret manager resolution.
- Register a secret resolver plugin in the Plugin Registry.
- Configure `PLUGIN_GATEWAY_TOKEN` and `SERVICE_TOKEN` for service auth.

### Vault (OSS) production guidance
Use HashiCorp Vault OSS for secret management (avoid Enterprise-only features).
Recommended baseline:
- Storage: use a durable backend (Raft integrated storage or supported external storage).
- TLS: enable TLS end-to-end; do not use dev mode in production.
- Auth: use short-lived tokens via auth methods (Kubernetes, OIDC) instead of long-lived root tokens.
- Policies: least-privilege policies per service; segregate read/write paths.
- Audit: enable audit devices (file/syslog) and forward to central logging.
- Rotation: rotate tokens regularly; use Vault Agent or sidecar where appropriate.

Autonoma integration:
- Register a `vault-resolver` secret plugin with `auth_ref=env:VAULT_TOKEN` and
  `auth_config.provider=vault` pointing to the Vault address and KV mount.
- Use `secretkeyref:plugin:vault-resolver:<mount>/<path>#<key>` for secret references.

## 7) Required configuration
Set these environment variables via secret manager or k8s secrets:
- `DATABASE_URL`
- `REDIS_URL`
- `KEYCLOAK_URL`
- `OIDC_ISSUER`
- `OIDC_CLIENT_ID`
- `OIDC_CLIENT_SECRET`
- `SERVICE_TOKEN`
- `PLUGIN_GATEWAY_TOKEN`
- `AUDIT_INGEST_TOKEN`
- `OTEL_EXPORTER_OTLP_ENDPOINT`
- `VECTOR_STORE_PROVIDER` and `WEAVIATE_URL` or `QDRANT_URL`
- `LLM_API_URL`, `LLM_MODEL`, and secret reference for API key

## 8) Deploy order
1. Data stores (Postgres, Redis, Vector DB)
2. Policy (OPA)
3. Plugin Gateway
4. API (runs migrations on startup)
5. Agent runtime
6. Web UI
7. Observability stack

## 9) Database migrations
Migrations run on API startup. For manual migrations:
```
make db-migrate
```
Run migrations before scaling the API to multiple replicas.

## 10) Scaling and HA
- Use `infra/k8s/base` as a starting point.
- Enable HPA for API, agent runtime, plugin gateway.
- Prefer external Postgres/Redis with HA.
- Scale agent runtime by load; ensure `SERVICE_TOKEN` and plugin gateway
  capacity scale accordingly.

## 11) Observability
- OTEL collector exports traces/metrics.
- Prometheus scrapes `otel-collector:8889`.
- Grafana dashboards live in `infra/grafana/dashboards/`.
- Audit events are stored in Postgres and can be forwarded:
  - Syslog via `AUDIT_FORWARD_SYSLOG=true`.
  - HTTP via `AUDIT_FORWARD_HTTP_URL`.

## 12) Backup and disaster recovery
- Postgres: scheduled backups (daily + PITR).
- Redis: snapshot if needed for memory continuity.
- Vector DB: snapshot/export as supported by provider.
- Store backups off-cluster with retention policies.

## 13) Upgrades and rollbacks
- Apply schema migrations in a maintenance window for major changes.
- Use rolling deployments for API and agent runtime.
- If rollback is required, revert the deployment and restore DB backup if needed.

## 13.1) Environment-specific deployment (Helm/Kustomize)
This section outlines a simple pattern for dev/stage/prod overlays.

### Kustomize
Directory layout:
```
infra/k8s/
  base/
  overlays/
    dev/
    stage/
    prod/
```
Example overlay:
```
infra/k8s/overlays/prod/kustomization.yaml
```
```yaml
resources:
  - ../../base
patchesStrategicMerge:
  - api-resources.yaml
  - agent-runtime-resources.yaml
configMapGenerator:
  - name: autonoma-config
    literals:
      - LOG_LEVEL=info
      - VECTOR_STORE_PROVIDER=weaviate
```

### Helm
If you prefer Helm, create a chart wrapper around `infra/k8s/base`:
```
charts/autonoma/
  Chart.yaml
  values.yaml
  templates/
```
Use values for environment overrides:
```
helm upgrade --install autonoma charts/autonoma -f values-prod.yaml
```

## 13.2) Day-2 operations
### Routine checks (daily)
- Verify API, agent runtime, plugin gateway health endpoints.
- Review audit logs for policy denies and authz failures.
- Check Grafana dashboards for error spikes and latency.

### Incident response
- Use correlation IDs to trace across API → agent runtime → plugin gateway.
- Extract audit events for affected actor_id/workspace.
- If approvals are stuck, verify approval service status and role mapping.

### Performance tuning
- Increase API and agent runtime replicas for peak load.
- Tune Redis size/eviction for short-term memory.
- Adjust vector DB resources based on index size and QPS.

### Key rotation
- Rotate `SERVICE_TOKEN` and `PLUGIN_GATEWAY_TOKEN` on a schedule.
- Update `api_key_ref` secrets in the secret manager and re-deploy.

### Cleanup and retention
- Configure audit retention policies in Postgres.
- Archive old runs and workflow history if needed.

## 14) Security checklist
- HTTPS enforced for all public endpoints.
- RBAC roles mapped in Keycloak.
- OPA default-deny policies deployed and tested.
- Secrets stored in secret manager; references only in configs.
- Audit logs enabled and forwarded.
- Correlation IDs verified end-to-end.

## 15) Validation
After deployment:
- Verify health endpoints.
- Login via UI and run a dev workflow.
- Trigger a prod workflow and verify approval flow.
- Check audit trail and Grafana dashboards.
