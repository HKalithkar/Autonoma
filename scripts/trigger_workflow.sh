#!/bin/sh
set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8000}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://localhost:8080}"
KEYCLOAK_REALM="${KEYCLOAK_REALM:-autonoma}"
OIDC_CLIENT_ID="${OIDC_CLIENT_ID:-autonoma-api}"
OIDC_CLIENT_SECRET="${OIDC_CLIENT_SECRET:-autonoma-api-secret}"

usage() {
  echo "Usage: $0 <workflow_id_or_name> [--env dev|stage|prod] [--params '{...}'] [--params-file path]" >&2
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

workflow_ref="$1"
shift

environment="dev"
params_json="{}"
params_file=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --env)
      environment="$2"
      shift 2
      ;;
    --params)
      params_json="$2"
      shift 2
      ;;
    --params-file)
      params_file="$2"
      shift 2
      ;;
    *)
      usage
      ;;
  esac
done

if [ -n "${params_file}" ] && [ "${params_json}" != "{}" ]; then
  echo "Use either --params or --params-file, not both." >&2
  exit 1
fi

if [ -n "${params_file}" ]; then
  if [ ! -f "${params_file}" ]; then
    echo "params file not found: ${params_file}" >&2
    exit 1
  fi
  params_json="$(cat "${params_file}")"
fi

USERNAME="$(prompt_user)"
PASSWORD="$(prompt_pass)"
TOKEN="$(get_token "${USERNAME}" "${PASSWORD}")"

is_uuid="$(printf "%s" "${workflow_ref}" | python3 -c 'import re,sys
print("yes" if re.match(r"^[0-9a-fA-F-]{36}$", sys.argv[1]) else "no")' "${workflow_ref}")"

workflow_id="${workflow_ref}"
if [ "${is_uuid}" != "yes" ]; then
  workflows_json="$(curl -sS -H "Authorization: Bearer ${TOKEN}" "${API_BASE}/v1/workflows")"
  workflow_id="$(printf "%s" "${workflows_json}" | python3 -c 'import json,sys
name = sys.argv[1]
for wf in json.load(sys.stdin):
    if wf.get("name") == name:
        print(wf.get("id") or "")
        break' "${workflow_ref}")"
fi

if [ -z "${workflow_id}" ]; then
  echo "workflow not found: ${workflow_ref}" >&2
  exit 1
fi

response="$(curl -sS -w "\n%{http_code}" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -X POST \
  -d "{\"environment\":\"${environment}\",\"params\":${params_json}}" \
  "${API_BASE}/v1/workflows/${workflow_id}/runs")"

body="$(printf "%s" "${response}" | sed '$d')"
code="$(printf "%s" "${response}" | tail -n 1)"
if [ "${code}" != "202" ]; then
  echo "run request failed: HTTP ${code}" >&2
  echo "${body}" >&2
  exit 1
fi

printf "%s\n" "${body}"
