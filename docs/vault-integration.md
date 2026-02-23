# Vault Integration (OSS)

This guide explains how to run HashiCorp Vault OSS in the dev stack, register it as a secret resolver plugin, and use Vault-backed secret references.

## 1) Start the engines stack (includes Vault)
```sh
make engines-up
```
Vault runs in a local single-node config (no TLS) and is initialized by `vault-init` with a KV v2 mount and sample secrets.
Vault data is persisted in the `vault_data` Docker volume, and the init metadata is stored in
`/vault/data/init.json` inside the volume.

Default dev settings (from `.env` / `.env.example`):
- `VAULT_ADDR=http://vault:8200`
- `VAULT_TOKEN=autonoma-dev-token`
- `VAULT_KV_MOUNT=kv`
- `VAULT_ROOT_TOKEN=` (optional override; normally stored in `/vault/data/init.json`)
- `AIRFLOW_PASSWORD_REF=secretkeyref:plugin:vault-resolver:kv/autonoma#airflow`
- `JENKINS_TOKEN_REF=secretkeyref:plugin:vault-resolver:kv/autonoma#jenkins`

## 2) Register the Vault secret resolver plugin
You can register via the helper script:
```sh
scripts/register_plugins_workflows.sh scripts/inputs/vault.json
```

Or register manually (requires a valid API bearer token):
```sh
curl -X POST http://localhost:8000/v1/plugins \
  -H "authorization: Bearer $TOKEN" \
  -H "content-type: application/json" \
  -d '{
    "name": "vault-resolver",
    "version": "v1",
    "plugin_type": "secret",
    "endpoint": "http://plugin-gateway:8002/invoke",
    "actions": { "resolve": { "description": "Resolve Vault secret" } },
    "auth_type": "bearer",
    "auth_ref": "env:VAULT_TOKEN",
    "auth_config": {
      "provider": "vault",
      "addr": "http://vault:8200",
      "mount": "kv"
    }
  }'
```

## 3) Store secrets in Vault
The dev init script seeds these example keys under `kv/autonoma`:
- `airflow`
- `jenkins`
- `mcp_token`
- `gitops`

To add your own:
```sh
docker compose -f infra/docker-compose.engines.yml exec -T vault \
  sh -lc 'VAULT_ADDR=http://127.0.0.1:8200 VAULT_TOKEN=dev-root vault kv put kv/autonoma my_key="my_value"'
```

## 4) Use secret references
Use this format anywhere secrets are accepted (plugins/workflows/LLM config):
```
secretkeyref:plugin:vault-resolver:kv/autonoma#airflow
```

### Example: workflow run params
```json
{
  "params": {
    "api_key": "secretkeyref:plugin:vault-resolver:kv/autonoma#airflow",
    "dag_id": "health"
  },
  "environment": "dev"
}
```

## 5) Run the Vault integration test
```sh
VAULT_ADDR=http://vault:8200 VAULT_TOKEN=autonoma-dev-token make test-vault
```
This target brings up the engines stack, runs the single integration test, and then tears the stack down.

## Troubleshooting
- **Vault unhealthy:** ensure `make engines-up` completed; check `docker compose -f infra/docker-compose.engines.yml ps`.
- **Secret not found:** confirm the KV path and key (format `kv/<path>#<key>`).
- **Auth errors:** verify `VAULT_TOKEN` is set and matches the token created by `vault-init`.
- **Networking:** integration test must run in the engines compose network (use `make test-vault`).

## Production note
Dev mode is in-memory and insecure. For production, use Vault OSS with durable storage, TLS, and short-lived tokens. See `docs/production-handbook.md`.
