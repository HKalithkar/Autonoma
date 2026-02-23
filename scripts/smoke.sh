#!/bin/sh
set -euo pipefail

API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-3000}"
OPA_PORT="${OPA_PORT:-8181}"
AGENT_RUNTIME_PORT="${AGENT_RUNTIME_PORT:-8001}"
PLUGIN_GATEWAY_PORT="${PLUGIN_GATEWAY_PORT:-8002}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://localhost:8080}"
KEYCLOAK_REALM="${KEYCLOAK_REALM:-autonoma}"
OIDC_CLIENT_ID="${OIDC_CLIENT_ID:-autonoma-api}"
OIDC_CLIENT_SECRET="${OIDC_CLIENT_SECRET:-autonoma-api-secret}"
ADMIN_USER="${SMOKE_ADMIN_USER:-demo_admin}"
ADMIN_PASS="${SMOKE_ADMIN_PASS:-demo_admin_pass}"
APPROVER_USER="${SMOKE_APPROVER_USER:-demo_approver}"
APPROVER_PASS="${SMOKE_APPROVER_PASS:-demo_approver_pass}"
SMOKE_APPROVALS="${SMOKE_APPROVALS:-0}"
API_BASE="http://localhost:${API_PORT}"
RUN_ENVIRONMENT="dev"

curl -fsS "${API_BASE}/healthz" > /dev/null
curl -fsS "http://localhost:${AGENT_RUNTIME_PORT}/healthz" > /dev/null
curl -fsS "http://localhost:${PLUGIN_GATEWAY_PORT}/healthz" > /dev/null
curl -fsS "http://localhost:${WEB_PORT}/" > /dev/null
curl -fsS "http://localhost:${OPA_PORT}/health" > /dev/null

for i in $(seq 1 20); do
  if curl -fsS "${KEYCLOAK_URL}/realms/${KEYCLOAK_REALM}" > /dev/null; then
    break
  fi
  if [ "${i}" -eq 20 ]; then
    echo "smoke failed: keycloak not ready" >&2
    exit 1
  fi
  sleep 1
done

get_token() {
  username="$1"
  password="$2"
  response="$(curl -sS -w "\n%{http_code}" \
    -X POST \
    -d "grant_type=password" \
    -d "client_id=${OIDC_CLIENT_ID}" \
    -d "client_secret=${OIDC_CLIENT_SECRET}" \
    -d "username=${username}" \
    -d "password=${password}" \
    "${KEYCLOAK_URL}/realms/${KEYCLOAK_REALM}/protocol/openid-connect/token")"
  if [ -z "${response}" ]; then
    echo "smoke failed: empty token response from Keycloak" >&2
    exit 1
  fi
  body="$(printf "%s" "${response}" | sed '$d')"
  code="$(printf "%s" "${response}" | tail -n 1)"
  if [ "${code}" != "200" ]; then
    echo "smoke failed: token request HTTP ${code}" >&2
    echo "${body}" >&2
    exit 1
  fi
  if ! token="$(printf "%s" "${body}" | python3 -c 'import json,sys
try:
    data = json.load(sys.stdin)
except json.JSONDecodeError:
    print("smoke failed: invalid token response JSON", file=sys.stderr)
    sys.exit(1)
token = data.get("access_token")
if not token:
    print("smoke failed: access_token missing in response", file=sys.stderr)
    sys.exit(1)
print(token)
')"; then
    echo "${body}" >&2
    exit 1
  fi
  printf "%s" "${token}"
}

ADMIN_TOKEN="$(get_token "${ADMIN_USER}" "${ADMIN_PASS}")"

WORKFLOW_NAME="smoke-workflow-$(python3 - <<'PY'
import uuid
print(uuid.uuid4().hex[:8])
PY
)"

plugins_response="$(curl -sS -w "\n%{http_code}" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  "${API_BASE}/v1/plugins")"
plugins_body="$(printf "%s" "${plugins_response}" | sed '$d')"
plugins_code="$(printf "%s" "${plugins_response}" | tail -n 1)"
if [ "${plugins_code}" != "200" ]; then
  echo "smoke failed: plugins list HTTP ${plugins_code}" >&2
  echo "${plugins_body}" >&2
  exit 1
fi

PLUGIN_ID="$(printf "%s" "${plugins_body}" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(next((p["id"] for p in data if p.get("name")=="airflow"), ""))')"

if [ -z "${PLUGIN_ID}" ]; then
  plugin_response="$(curl -sS -w "\n%{http_code}" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"airflow\",\"endpoint\":\"http://plugin-gateway:8002/invoke\",\"actions\":{\"trigger_dag\":{}}}" \
  "${API_BASE}/v1/plugins")"
  plugin_body="$(printf "%s" "${plugin_response}" | sed '$d')"
  plugin_code="$(printf "%s" "${plugin_response}" | tail -n 1)"
  if [ "${plugin_code}" != "201" ]; then
    echo "smoke failed: plugin register HTTP ${plugin_code}" >&2
    echo "${plugin_body}" >&2
    exit 1
  fi
  PLUGIN_ID="$(printf "%s" "${plugin_body}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
fi

workflow_response="$(curl -sS -w "\n%{http_code}" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"${WORKFLOW_NAME}\",\"plugin_id\":\"${PLUGIN_ID}\",\"action\":\"trigger_dag\"}" \
  "${API_BASE}/v1/workflows")"
workflow_body="$(printf "%s" "${workflow_response}" | sed '$d')"
workflow_code="$(printf "%s" "${workflow_response}" | tail -n 1)"
if [ "${workflow_code}" != "201" ]; then
  echo "smoke failed: workflow register HTTP ${workflow_code}" >&2
  echo "${workflow_body}" >&2
  exit 1
fi
WORKFLOW_ID="$(printf "%s" "${workflow_body}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
SMOKE_CLEANUP="1"

if [ "${SMOKE_APPROVALS}" = "1" ]; then
  RUN_ENVIRONMENT="prod"
fi

run_response="$(curl -sS -w "\n%{http_code}" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"params\":{\"dag_id\":\"smoke\"},\"environment\":\"${RUN_ENVIRONMENT}\"}" \
  "${API_BASE}/v1/workflows/${WORKFLOW_ID}/runs")"
RUN_BODY="$(printf "%s" "${run_response}" | sed '$d')"
RUN_CODE="$(printf "%s" "${run_response}" | tail -n 1)"
if [ "${RUN_CODE}" != "202" ]; then
  echo "smoke failed: run trigger HTTP ${RUN_CODE}" >&2
  echo "${RUN_BODY}" >&2
  exit 1
fi

RUN_ID="$(printf "%s" "${RUN_BODY}" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(data.get("run_id", ""))'
)"

if [ -z "${RUN_ID}" ]; then
  echo "smoke failed: run_id missing"
  exit 1
fi

if [ "${SMOKE_APPROVALS}" = "1" ]; then
  APPROVAL_ID="$(printf "%s" "${RUN_BODY}" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(data.get("approval_id", ""))'
)"
  if [ -z "${APPROVAL_ID}" ]; then
    echo "smoke failed: approval_id missing (expected approvals for prod run)"
    exit 1
  fi
  APPROVER_TOKEN="$(get_token "${APPROVER_USER}" "${APPROVER_PASS}")"
  curl -fsS \
    -H "Authorization: Bearer ${APPROVER_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"decision\":\"approve\"}" \
    "${API_BASE}/v1/approvals/${APPROVAL_ID}/decision" > /dev/null
else
  echo "smoke note: approvals flow skipped (set SMOKE_APPROVALS=1 to enable)"
fi

agent_response="$(curl -sS -w "\n%{http_code}" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"goal\":\"Trigger workflow to refresh caches\",\"environment\":\"dev\",\"tools\":[\"plugin_gateway.invoke\"]}" \
  "${API_BASE}/v1/agent/runs")"
agent_body="$(printf "%s" "${agent_response}" | sed '$d')"
agent_code="$(printf "%s" "${agent_response}" | tail -n 1)"
if [ "${agent_code}" != "201" ]; then
  echo "smoke failed: agent run HTTP ${agent_code}" >&2
  echo "${agent_body}" >&2
  exit 1
fi

agent_prod_response="$(curl -sS -w "\n%{http_code}" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"goal\":\"Refresh caches safely\",\"environment\":\"prod\",\"tools\":[\"plugin_gateway.invoke\"]}" \
  "${API_BASE}/v1/agent/runs")"
agent_prod_body="$(printf "%s" "${agent_prod_response}" | sed '$d')"
agent_prod_code="$(printf "%s" "${agent_prod_response}" | tail -n 1)"
if [ "${agent_prod_code}" != "201" ]; then
  echo "smoke failed: agent prod run HTTP ${agent_prod_code}" >&2
  echo "${agent_prod_body}" >&2
  exit 1
fi

AGENT_VERDICT="$(printf "%s" "${agent_prod_body}" | python3 -c 'import json,sys; data=json.load(sys.stdin); eval=data.get("evaluation") or {}; print(eval.get("verdict", ""))')"
if [ -z "${AGENT_VERDICT}" ]; then
  echo "smoke failed: agent evaluation verdict missing" >&2
  echo "${agent_prod_body}" >&2
  exit 1
fi

if [ "${AGENT_VERDICT}" = "require_approval" ]; then
  AGENT_APPROVAL_ID="$(printf "%s" "${agent_prod_body}" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(data.get("approval_id", ""))')"
  if [ -z "${AGENT_APPROVAL_ID}" ]; then
    echo "smoke failed: agent approval_id missing for prod run" >&2
    exit 1
  fi
  APPROVER_TOKEN="$(get_token "${APPROVER_USER}" "${APPROVER_PASS}")"
  approval_response="$(curl -sS -w "\n%{http_code}" \
    -H "Authorization: Bearer ${APPROVER_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"decision\":\"approve\"}" \
    "${API_BASE}/v1/approvals/${AGENT_APPROVAL_ID}/decision")"
  approval_body="$(printf "%s" "${approval_response}" | sed '$d')"
  approval_code="$(printf "%s" "${approval_response}" | tail -n 1)"
  if [ "${approval_code}" != "200" ]; then
    echo "smoke failed: agent approval decision HTTP ${approval_code}" >&2
    echo "${approval_body}" >&2
    exit 1
  fi
else
  echo "smoke note: agent prod verdict ${AGENT_VERDICT}"
fi

agent_deny_response="$(curl -sS -w "\n%{http_code}" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"goal\":\"Delete production clusters\",\"environment\":\"prod\",\"tools\":[\"plugin_gateway.invoke\"]}" \
  "${API_BASE}/v1/agent/runs")"
agent_deny_body="$(printf "%s" "${agent_deny_response}" | sed '$d')"
agent_deny_code="$(printf "%s" "${agent_deny_response}" | tail -n 1)"
if [ "${agent_deny_code}" != "403" ]; then
  echo "smoke failed: agent deny expected 403, got ${agent_deny_code}" >&2
  echo "${agent_deny_body}" >&2
  exit 1
fi

if [ "${SMOKE_CLEANUP}" = "1" ]; then
  cleanup_response="$(curl -sS -w "\n%{http_code}" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    -X DELETE \
    "${API_BASE}/v1/workflows/${WORKFLOW_ID}")"
  cleanup_body="$(printf "%s" "${cleanup_response}" | sed '$d')"
  cleanup_code="$(printf "%s" "${cleanup_response}" | tail -n 1)"
  if [ "${cleanup_code}" != "200" ]; then
    echo "smoke failed: workflow cleanup HTTP ${cleanup_code}" >&2
    echo "${cleanup_body}" >&2
    exit 1
  fi
fi

echo "smoke ok"
