#!/bin/sh
set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8000}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://localhost:8080}"
KEYCLOAK_REALM="${KEYCLOAK_REALM:-autonoma}"
OIDC_CLIENT_ID="${OIDC_CLIENT_ID:-autonoma-api}"
OIDC_CLIENT_SECRET="${OIDC_CLIENT_SECRET:-autonoma-api-secret}"

usage() {
  echo "Usage: $0 <input.json> [input.json ...]" >&2
  exit 1
}

if [ "$#" -lt 1 ]; then
  usage
fi

prompt_user() {
  if [ -n "${API_USER:-}" ]; then
    printf "%s" "${API_USER}"
    return
  fi
  printf "Username: " >&2
  read -r username
  printf "%s" "$username"
}

prompt_pass() {
  if [ -n "${API_PASS:-}" ]; then
    printf "%s" "${API_PASS}"
    return
  fi
  printf "Password: " >&2
  stty -echo
  read -r password
  stty echo
  printf "\n" >&2
  printf "%s" "$password"
}

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
  body="$(printf "%s" "${response}" | sed '$d')"
  code="$(printf "%s" "${response}" | tail -n 1)"
  if [ "${code}" != "200" ]; then
    echo "token request failed: HTTP ${code}" >&2
    echo "${body}" >&2
    exit 1
  fi
  printf "%s" "${body}" | python3 -c 'import json,sys
try:
    data = json.load(sys.stdin)
except json.JSONDecodeError:
    print("token response invalid JSON", file=sys.stderr)
    sys.exit(1)
token = data.get("access_token")
if not token:
    print("token response missing access_token", file=sys.stderr)
    sys.exit(1)
print(token)'
}

get_plugin_id() {
  plugin_name="$1"
  printf "%s" "$2" | python3 -c 'import json,sys
name = sys.argv[1]
data = json.load(sys.stdin)
for plugin in data:
    if plugin.get("name") == name:
        print(plugin.get("id") or "")
        break' "$plugin_name"
}

workflow_exists() {
  workflow_name="$1"
  printf "%s" "$2" | python3 -c 'import json,sys
name = sys.argv[1]
workflows = json.load(sys.stdin)
for workflow in workflows:
    if workflow.get("name") == name:
        print("yes")
        break' "$workflow_name"
}

USERNAME="$(prompt_user)"
PASSWORD="$(prompt_pass)"
TOKEN="$(get_token "${USERNAME}" "${PASSWORD}")"

for input_file in "$@"; do
  if [ ! -f "${input_file}" ]; then
    echo "missing input file: ${input_file}" >&2
    exit 1
  fi

  plugin_payload="$(python3 - "${input_file}" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    data = json.load(handle)

print(json.dumps(data.get("plugin", {})))
PY
)"

  plugin_name="$(printf "%s" "${plugin_payload}" | python3 -c 'import json,sys
payload = json.load(sys.stdin)
print(payload.get("name", ""))')"

  if [ -z "${plugin_name}" ]; then
    echo "missing plugin.name in ${input_file}" >&2
    exit 1
  fi

  plugins_json="$(curl -sS \
    -H "Authorization: Bearer ${TOKEN}" \
    "${API_BASE}/v1/plugins")"

  plugin_id="$(get_plugin_id "${plugin_name}" "${plugins_json}")"

  if [ -z "${plugin_id}" ]; then
    plugin_response="$(curl -sS -w "\n%{http_code}" \
      -H "Authorization: Bearer ${TOKEN}" \
      -H "Content-Type: application/json" \
      -d "${plugin_payload}" \
      "${API_BASE}/v1/plugins")"
    plugin_body="$(printf "%s" "${plugin_response}" | sed '$d')"
    plugin_code="$(printf "%s" "${plugin_response}" | tail -n 1)"
    if [ "${plugin_code}" != "201" ]; then
      echo "plugin register failed (${plugin_name}): HTTP ${plugin_code}" >&2
      echo "${plugin_body}" >&2
      exit 1
    fi
    plugin_id="$(printf "%s" "${plugin_body}" | python3 -c 'import json,sys
payload = json.load(sys.stdin)
print(payload.get("id", ""))')"
  fi

  if [ -z "${plugin_id}" ]; then
    echo "missing plugin id for ${plugin_name}" >&2
    exit 1
  fi

  workflows_json="$(curl -sS \
    -H "Authorization: Bearer ${TOKEN}" \
    "${API_BASE}/v1/workflows")"

  python3 - "${input_file}" <<'PY' | while IFS= read -r workflow_payload; do
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    data = json.load(handle)

for workflow in data.get("workflows", []):
    print(json.dumps(workflow))
PY
    workflow_name="$(printf "%s" "${workflow_payload}" | python3 -c 'import json,sys
payload = json.load(sys.stdin)
print(payload.get("name", ""))')"
    if [ -z "${workflow_name}" ]; then
      echo "missing workflow name in ${input_file}" >&2
      exit 1
    fi

    exists="$(workflow_exists "${workflow_name}" "${workflows_json}")"
    if [ "${exists}" = "yes" ]; then
      echo "workflow already exists: ${workflow_name}" >&2
      continue
    fi

    payload_with_plugin="$(printf "%s" "${workflow_payload}" | python3 -c 'import json,sys
plugin_id = sys.argv[1]
workflow = json.load(sys.stdin)
workflow["plugin_id"] = plugin_id
print(json.dumps(workflow))' "${plugin_id}")"

    workflow_response="$(curl -sS -w "\n%{http_code}" \
      -H "Authorization: Bearer ${TOKEN}" \
      -H "Content-Type: application/json" \
      -d "${payload_with_plugin}" \
      "${API_BASE}/v1/workflows")"
    workflow_body="$(printf "%s" "${workflow_response}" | sed '$d')"
    workflow_code="$(printf "%s" "${workflow_response}" | tail -n 1)"
    if [ "${workflow_code}" != "201" ]; then
      echo "workflow register failed (${workflow_name}): HTTP ${workflow_code}" >&2
      echo "${workflow_body}" >&2
      exit 1
    fi
    echo "workflow registered: ${workflow_name}" >&2
  done

done

printf "done\n" >&2
