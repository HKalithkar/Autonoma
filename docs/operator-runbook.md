# Operator Runbook

This runbook describes how to operate Autonoma in dev and production-like
environments.

## Prerequisites
- Docker + Docker Compose for local dev.
- Postgres, Redis, and OPA reachable by the API.
- Plugin Gateway reachable by API and agent-runtime.
- Keycloak (OIDC) realm configured and reachable by the web UI and API.

## Start/stop
Local dev:
```
make up
```

Stop:
```
make down
```

## Database migrations
Run migrations before the API serves traffic:
```
make db-migrate
```

If API starts without migrations, workflows/runs will fail with missing table
errors.

## Health checks
- API: `GET /healthz`
- Agent runtime: `GET /healthz`
- Plugin gateway: `GET /healthz`
- Policy (OPA): `GET /health`
- Web: `GET /`

## Auth/OIDC
- Ensure Keycloak is reachable at `KEYCLOAK_URL`.
- The API requires a valid token for all endpoints.
- Web UI redirects to Keycloak for login.

## Secrets and LLM configuration
- LLM API key references must use:
  - `env:VAR_NAME`
  - `secretkeyref:plugin:<name>:<path>`
- Secret references are resolved through the API secret resolver and Plugin
  Gateway. Ensure `PLUGIN_GATEWAY_TOKEN`/`SERVICE_TOKEN` are configured.
- In production, point to your secret manager plugin (Vault, AWS, GCP).

## Observability
- OTEL collector exports traces and metrics.
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3001`
- Audit events are stored in Postgres and visible in the UI.

## Troubleshooting
### API fails on startup
- Confirm `make db-migrate` ran successfully.
- Check `DATABASE_URL` in `.env`.

### Keycloak HTTPS errors
- For local dev, use `KC_HOSTNAME_STRICT=false` and `KC_HOSTNAME_STRICT_HTTPS=false`.
- Ensure `KEYCLOAK_URL` points to the correct protocol.

### Plugin gateway failures
- Verify plugin registry entries exist.
- Confirm `PLUGIN_GATEWAY_TOKEN` is set and matches API config.

### LLM errors
- Check `LLM_API_URL`, `LLM_MODEL`, and `LLM_API_KEY` or the configured
  `api_key_ref`.
- Verify the secret resolver endpoint is reachable by agent-runtime.

## Backups and recovery
- Backup Postgres regularly (workflow registry, approvals, audit).
- Restore by reloading Postgres and running `make db-migrate`.

## Production hardening checklist
- Enforce HTTPS on Keycloak and API.
- Enable TLS for database connections.
- Configure secret plugins and remove raw secrets from `.env`.
- Apply k8s HPA and resource limits from `infra/k8s/base`.
