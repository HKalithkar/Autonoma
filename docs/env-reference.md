# Environment Variables Reference

This document explains each key in `.env` / `.env.example`. Values are examples for local dev.

## Core services
- `API_PORT`: Host port for API service (container listens on 8000).
- `AGENT_RUNTIME_PORT`: Host port for agent-runtime service (container listens on 8001).
- `AGENT_RUNTIME_URL`: Internal URL used by API to reach agent-runtime.
- `PLUGIN_GATEWAY_PORT`: Host port for plugin-gateway service (container listens on 8002).
- `WORKFLOW_ADAPTER_PORT`: Host port for workflow-adapter service (container listens on 9004).
- `WEB_PORT`: Host port for the web UI (container listens on 3000).
- `OPA_PORT`: Host port for OPA policy service (container listens on 8181).
- `SERVICE_NAME`: Service identifier used in logs/metrics (API defaults to `api`).
- `ENVIRONMENT`: Environment label (`dev`, `stage`, `prod`).

## API + DB
- `DATABASE_URL`: SQLAlchemy DB URL for Postgres.
- `DB_AUTO_CREATE`: Auto-create tables on startup (dev only).
- `DB_SEED`: Seed reference data on startup (dev only).

## Redis
- `REDIS_PORT`: Host port for Redis.

## Auth / Keycloak / IAM
- `KEYCLOAK_ADMIN`: Keycloak admin username.
- `KEYCLOAK_ADMIN_PASSWORD`: Keycloak admin password.
- `OIDC_ISSUER`: OIDC issuer URL.
- `OIDC_AUTH_URL`: OIDC authorization URL (used by browser flow).
- `OIDC_AUTH_URL_DOCKER`: OIDC authorization URL from inside containers.
- `OIDC_TOKEN_URL`: OIDC token URL.
- `OIDC_JWKS_URL`: OIDC JWKS URL.
- `OIDC_CLIENT_ID`: OIDC client id for API.
- `OIDC_CLIENT_SECRET`: OIDC client secret.
- `OIDC_REDIRECT_URI`: OIDC redirect URI for API callback.
- `OIDC_AUDIENCE`: Expected audience for OIDC tokens.
- `OIDC_SCOPES`: OIDC scopes to request.
- `OIDC_ALLOWED_ALGS`: Allowed JWT signing algorithms.
- `AUTH_COOKIE_SECURE`: Whether auth cookies are marked `Secure`.
- `OIDC_REVOCATION_URL`: Optional OIDC token revocation endpoint (used on logout).
- `AUTH_REFRESH_MAX_AGE`: Max age (seconds) for refresh token cookie (fallback if IdP omits refresh expiry).
- `AUTH_REFRESH_RATE_LIMIT_MAX`: Max refresh attempts per window (default `6`).
- `AUTH_REFRESH_RATE_LIMIT_WINDOW`: Refresh rate limit window in seconds (default `60`).
- `IAM_PROVIDER`: IAM provider name (e.g., `keycloak`).
- `IAM_ADMIN_URL`: IAM admin base URL.
- `IAM_TOKEN_URL`: IAM token endpoint.
- `IAM_CLIENT_ID`: IAM client id for admin operations.
- `IAM_CLIENT_SECRET`: IAM client secret for admin operations.
- `IAM_REALM`: IAM realm name.

## URLs used by services
- `UI_BASE_URL`: Base URL for UI redirects and links.
- `OPA_URL`: Internal URL for OPA policy service.
- `PLUGIN_GATEWAY_URL`: Internal URL for plugin gateway invoke endpoint.
- `WORKFLOW_ADAPTER_URL`: Internal URL used by seed data as workflow plugin forward target (`auth_config.invoke_url`).
- `RUNTIME_ORCHESTRATOR_URL`: Internal URL for runtime-orchestrator service.
- `RUNTIME_ORCHESTRATOR_ENABLE_EVENT_BUS`: Enables orchestrator event publish path.
- `NATS_URL`: NATS server URL used for JetStream event publishing.
- `RUNTIME_EVENTS_SUBJECT`: Subject used for runtime event publish.
- `RUNTIME_EVENTS_STREAM`: JetStream stream name for runtime events.
- `AIRFLOW_URL`: Internal URL for Airflow API.
- `JENKINS_URL`: Internal URL for Jenkins API.
- `N8N_BASE_URL`: Internal URL for n8n API/webhook endpoint.
- `WORKFLOW_STATUS_CALLBACK_URL`: Internal API callback endpoint used by workflow-adapter to report terminal workflow status.

## Concurrency and HTTP tuning
- `API_UVICORN_WORKERS`: Uvicorn worker count for API.
- `PLUGIN_GATEWAY_UVICORN_WORKERS`: Uvicorn worker count for plugin-gateway.
- `WORKFLOW_ADAPTER_UVICORN_WORKERS`: Uvicorn worker count for workflow-adapter.
- `PLUGIN_GATEWAY_HTTP_MAX_ATTEMPTS`: Max retry attempts for gateway outbound HTTP.
- `PLUGIN_GATEWAY_HTTP_RETRY_BACKOFF_SECONDS`: Backoff base seconds for gateway retry.
- `PLUGIN_GATEWAY_HTTP_MAX_CONNECTIONS`: Async HTTP connection pool max for gateway.
- `PLUGIN_GATEWAY_HTTP_MAX_KEEPALIVE_CONNECTIONS`: Keepalive pool max for gateway.

## Airflow / Jenkins / n8n
- `AIRFLOW_USERNAME`: Airflow basic auth username.
- `AIRFLOW_PORT`: Host port for Airflow UI.
- `JENKINS_USER`: Jenkins username.
- `JENKINS_PORT`: Host port for Jenkins UI.
- `N8N_IMAGE_TAG`: Docker tag for the n8n image used by the engines stack.
- `N8N_PORT`: Host port for n8n UI/webhooks.
- `N8N_EDITOR_BASE_URL`: Public editor URL for n8n.
- `N8N_WEBHOOK_URL`: Public webhook URL prefix used by n8n.
- `N8N_SECURE_COOKIE`: Set `false` for local HTTP access (no TLS) to avoid secure-cookie login errors.
- `N8N_PRESET_OWNER_EMAIL`: Seeded n8n owner email used by bootstrap on first startup.
- `N8N_PRESET_OWNER_PASSWORD`: Seeded n8n owner password used by bootstrap on first startup.
- `N8N_PRESET_OWNER_FIRST_NAME`: Seeded n8n owner first name.
- `N8N_PRESET_OWNER_LAST_NAME`: Seeded n8n owner last name.
- `AIRFLOW_PASSWORD_REF`: Secret ref for Airflow password (`secretkeyref:` or `env:`).
- `JENKINS_TOKEN_REF`: Secret ref for Jenkins API token (`secretkeyref:` or `env:`).

## Vault (OSS)
- `VAULT_ADDR`: Internal Vault URL used by plugin gateway.
- `VAULT_PORT`: Host port for Vault dev server.
- `VAULT_ROOT_TOKEN`: Optional root token override (dev only; normally stored in Vault init file).
- `VAULT_TOKEN`: Autonoma token used by the Vault resolver plugin.
- `VAULT_KV_MOUNT`: KV v2 mount name (default `kv`).
- `VAULT_INTEGRATION_TESTS`: Set `1` to enable the Vault integration test.

## LLM configuration
- `CHAT_AGENT_RUNTIME_TIMEOUT`: Timeout (seconds) for API to call agent-runtime chat.
- `LLM_API_KEY`: API key for the LLM provider (dev only; prefer secret refs in prod).
- `LLM_API_URL`: LLM provider base URL.
- `LLM_MODEL`: Default model id.
- `LLM_OVERRIDES_PATH`: JSON file path for per-agent overrides.
- `LLM_LOG_SUMMARY`: Whether to log a short LLM response summary.
- `LLM_TIMEOUT_SECONDS`: Timeout (seconds) for LLM provider calls.
- `LLM_TRACE_PREVIEW_CHARS`: Max chars stored in OTEL span previews for LLM input/output.
- `LLM_TRACE_FULL`: When `true`, Langfuse OTEL attributes include full LLM input/output.

## Secret resolution
- `SECRET_RESOLVER_URL`: API endpoint used by agent-runtime to resolve secrets.
- `SECRET_RESOLVER_TIMEOUT`: Timeout (seconds) for secret resolution calls.
- `SECRET_STORE_MAP`: Dev-only inline secret map for plugin gateway secret resolution.

## Audit + service tokens
- `AUDIT_INGEST_URL`: API endpoint for ingesting audit events from other services.
- `AUDIT_INGEST_TOKEN`: Shared token for audit ingest.
- `SERVICE_TOKEN`: Shared token for service-to-service auth.
- `PLUGIN_GATEWAY_TOKEN`: Token used to call Plugin Gateway.

## Audit forwarding
- `AUDIT_FORWARD_SYSLOG`: Enable syslog forwarding of audit events.
- `AUDIT_SYSLOG_HOST`: Syslog host.
- `AUDIT_SYSLOG_PORT`: Syslog port.
- `AUDIT_SYSLOG_PROTOCOL`: Syslog protocol (`udp`/`tcp`).
- `AUDIT_FORWARD_HTTP_URL`: HTTP endpoint to forward audit events.
- `AUDIT_FORWARD_HTTP_HEADERS`: JSON headers for HTTP forwarding.
- `AUDIT_FORWARD_HTTP_TIMEOUT`: Timeout for HTTP forwarding.

## Observability
- `OTEL_EXPORTER_OTLP_ENDPOINT`: OTEL collector endpoint.
- `OTEL_COLLECTOR_CONFIG`: OTEL collector config path inside the container.
- `LANGFUSE_OTLP_ENDPOINT`: Langfuse OTLP HTTP endpoint (base path; exporter appends `/v1/traces`).
- `LANGFUSE_OTLP_AUTH_HEADER`: Authorization header for Langfuse OTLP (`Basic <base64(public:secret)>`).
- `CORS_ALLOW_ORIGINS`: Comma-separated list of allowed browser origins (e.g. `http://server-ip:3000`). Required when UI is accessed from another host.
- `AUTH_COOKIE_SAMESITE`: Cookie SameSite policy (`lax`, `strict`, `none`). Use `none` only with HTTPS and `AUTH_COOKIE_SECURE=true`.
- `PROMETHEUS_PORT`: Host port for Prometheus.
- `GRAFANA_PORT`: Host port for Grafana.
- `GRAFANA_ADMIN_USER`: Grafana admin user.
- `GRAFANA_ADMIN_PASSWORD`: Grafana admin password.

## Langfuse (self-hosted)
- `LANGFUSE_PORT`: Host port for Langfuse web UI.
- `LANGFUSE_WEB_URL`: Public URL used by Langfuse web/worker.
- `LANGFUSE_DATABASE_URL`: Langfuse Postgres connection URL.
- `LANGFUSE_DB_USER`: Langfuse Postgres user.
- `LANGFUSE_DB_PASSWORD`: Langfuse Postgres password.
- `LANGFUSE_DB_NAME`: Langfuse Postgres database name.
- `LANGFUSE_DB_PORT`: Host port for Langfuse Postgres (mapped to 5432 in container).
- `LANGFUSE_POSTGRES_VERSION`: Postgres image tag for Langfuse.
- `LANGFUSE_CLICKHOUSE_USER`: ClickHouse user for Langfuse.
- `LANGFUSE_CLICKHOUSE_PASSWORD`: ClickHouse password for Langfuse.
- `LANGFUSE_CLICKHOUSE_HTTP_PORT`: Host port for ClickHouse HTTP (mapped to 8123).
- `LANGFUSE_CLICKHOUSE_TCP_PORT`: Host port for ClickHouse TCP (mapped to 9000).
- `LANGFUSE_REDIS_PASSWORD`: Redis password for Langfuse.
- `LANGFUSE_REDIS_PORT`: Host port for Langfuse Redis (mapped to 6379).
- `LANGFUSE_MINIO_ACCESS_KEY`: MinIO access key for Langfuse.
- `LANGFUSE_MINIO_SECRET_KEY`: MinIO secret key for Langfuse.
- `LANGFUSE_MINIO_PORT`: Host port for MinIO S3 API (mapped to 9000).
- `LANGFUSE_MINIO_CONSOLE_PORT`: Host port for MinIO console (mapped to 9001).
- `LANGFUSE_MINIO_ENDPOINT`: Internal MinIO endpoint used by Langfuse.
- `LANGFUSE_S3_EVENT_UPLOAD_BUCKET`: S3 bucket for Langfuse event uploads.
- `LANGFUSE_S3_MEDIA_UPLOAD_BUCKET`: S3 bucket for Langfuse media uploads.
- `LANGFUSE_S3_EVENT_UPLOAD_PREFIX`: S3 prefix for event uploads.
- `LANGFUSE_S3_MEDIA_UPLOAD_PREFIX`: S3 prefix for media uploads.
- `LANGFUSE_SALT`: Langfuse salt (required).
- `LANGFUSE_ENCRYPTION_KEY`: Langfuse encryption key (required; 64 hex chars).
- `LANGFUSE_NEXTAUTH_SECRET`: NextAuth secret (required).
- `LANGFUSE_PUBLIC_KEY`: Dev-only Langfuse public key for seeded project.
- `LANGFUSE_SECRET_KEY`: Dev-only Langfuse secret key for seeded project.
- `LANGFUSE_PUBLIC_KEY_REF`: Vault secret ref for Langfuse public key.
- `LANGFUSE_SECRET_KEY_REF`: Vault secret ref for Langfuse secret key.
- `LANGFUSE_INIT_ORG_ID`: Initial Langfuse org id (seed on first startup).
- `LANGFUSE_INIT_ORG_NAME`: Initial Langfuse org name.
- `LANGFUSE_INIT_PROJECT_ID`: Initial Langfuse project id.
- `LANGFUSE_INIT_PROJECT_NAME`: Initial Langfuse project name.
- `LANGFUSE_INIT_PROJECT_PUBLIC_KEY`: Initial Langfuse project public key.
- `LANGFUSE_INIT_PROJECT_SECRET_KEY`: Initial Langfuse project secret key.
- `LANGFUSE_INIT_USER_EMAIL`: Initial Langfuse admin email.
- `LANGFUSE_INIT_USER_NAME`: Initial Langfuse admin name.
- `LANGFUSE_INIT_USER_PASSWORD`: Initial Langfuse admin password.

## UI (Vite)
- `VITE_API_URL`: Override API base URL for the UI.
- `VITE_GRAFANA_URL`: Grafana URL for UI links.
- `VITE_KEYCLOAK_ADMIN_URL`: Keycloak admin URL for UI links.
- `VITE_SUPPORT_URL`: Support/help URL for UI links.

## Vector store / memory
- `VECTOR_STORE_PROVIDER`: `weaviate`, `qdrant`, or `disabled`.
- `VECTOR_COLLECTION`: Vector collection/index name.
- `WEAVIATE_URL`: Weaviate base URL.
- `QDRANT_URL`: Qdrant base URL.
- `EMBEDDING_PROVIDER`: Embedding provider (default `hash` for dev).
- `MEMORY_SEARCH_TOP_K`: Number of results returned for memory searches.

## GitOps
- `GITOPS_WEBHOOK_URL`: API webhook endpoint for GitOps callbacks.
- `GITOPS_WEBHOOK_TOKEN`: Shared token for GitOps webhooks.
