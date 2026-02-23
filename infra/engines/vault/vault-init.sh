#!/bin/sh
set -euo pipefail

VAULT_ADDR="${VAULT_ADDR:-http://vault:8200}"
VAULT_ROOT_TOKEN="${VAULT_ROOT_TOKEN:-}"
VAULT_AUTONOMA_TOKEN="${VAULT_AUTONOMA_TOKEN:-autonoma-dev-token}"
VAULT_KV_MOUNT="${VAULT_KV_MOUNT:-kv}"
VAULT_AIRFLOW_PASSWORD="${VAULT_AIRFLOW_PASSWORD:-admin}"
VAULT_JENKINS_TOKEN="${VAULT_JENKINS_TOKEN:-admin}"
VAULT_LANGFUSE_PUBLIC_KEY="${VAULT_LANGFUSE_PUBLIC_KEY:-}"
VAULT_LANGFUSE_SECRET_KEY="${VAULT_LANGFUSE_SECRET_KEY:-}"
VAULT_LANGFUSE_OTLP_AUTH_HEADER="${VAULT_LANGFUSE_OTLP_AUTH_HEADER:-}"
POLICY_PATH="${POLICY_PATH:-/vault/config/autonoma-policy.hcl}"
INIT_FILE="/vault/data/init.json"

wait_for_vault() {
  i=0
  while [ "$i" -lt 30 ]; do
    set +e
    VAULT_ADDR="${VAULT_ADDR}" vault status >/dev/null 2>&1
    code=$?
    set -e
    if [ "$code" -eq 0 ] || [ "$code" -eq 2 ]; then
      return 0
    fi
    i=$((i + 1))
    sleep 1
  done
  echo "vault did not become healthy" >&2
  exit 1
}

wait_for_vault

export VAULT_ADDR

if [ -w "/vault/data" ]; then
  chown -R 100:100 /vault/data || true
fi

init_vault() {
  init_payload=""
  if [ -f "${INIT_FILE}" ]; then
    init_payload="$(cat "${INIT_FILE}" || true)"
  fi
  if [ -z "${init_payload}" ]; then
    init_payload="$(vault operator init -format=json -key-shares=1 -key-threshold=1)"
    printf "%s" "${init_payload}" >"${INIT_FILE}"
  fi
  unseal_key="$(awk '
    found { gsub(/[", ]/, "", $0); print; exit }
    /"unseal_keys_b64"/ { found=1 }
  ' "${INIT_FILE}")"
  root_token="$(awk -F'\"' '/\"root_token\"/ { print $4; exit }' "${INIT_FILE}")"
  if [ -n "${VAULT_ROOT_TOKEN}" ]; then
    root_token="${VAULT_ROOT_TOKEN}"
  fi
  if [ -z "${unseal_key}" ] || [ -z "${root_token}" ]; then
    echo "vault init file missing keys" >&2
    exit 1
  fi
  vault operator unseal "${unseal_key}" >/dev/null 2>&1 || true
  export VAULT_TOKEN="${root_token}"
}

init_vault

if ! vault secrets list -format=json | grep -q "\"${VAULT_KV_MOUNT}/\""; then
  vault secrets enable -path="${VAULT_KV_MOUNT}" kv-v2
fi

vault policy write autonoma-secret "${POLICY_PATH}"
if ! vault token lookup "${VAULT_AUTONOMA_TOKEN}" >/dev/null 2>&1; then
  vault token create -policy=autonoma-secret -id="${VAULT_AUTONOMA_TOKEN}" -orphan >/dev/null
fi

vault kv put "${VAULT_KV_MOUNT}/autonoma" \
  airflow="${VAULT_AIRFLOW_PASSWORD}" \
  jenkins="${VAULT_JENKINS_TOKEN}" \
  mcp_token="mcp-dev-token" \
  gitops="gitops-dev-token" >/dev/null

if [ -n "${VAULT_LANGFUSE_PUBLIC_KEY}" ] && [ -n "${VAULT_LANGFUSE_SECRET_KEY}" ]; then
  vault kv put "${VAULT_KV_MOUNT}/langfuse" \
    public_key="${VAULT_LANGFUSE_PUBLIC_KEY}" \
    secret_key="${VAULT_LANGFUSE_SECRET_KEY}" \
    otlp_auth_header="${VAULT_LANGFUSE_OTLP_AUTH_HEADER}" >/dev/null
fi

echo "vault init complete"
