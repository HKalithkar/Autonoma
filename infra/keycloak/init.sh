#!/bin/bash
set -euo pipefail

KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak:8080}"
ADMIN_USER="${KEYCLOAK_ADMIN:-admin}"
ADMIN_PASS="${KEYCLOAK_ADMIN_PASSWORD:-admin_dev}"

ready=0
for i in $(seq 1 30); do
  if bash -c 'echo > /dev/tcp/keycloak/8080' > /dev/null 2>&1; then
    if ./opt/keycloak/bin/kcadm.sh config credentials \
      --server "${KEYCLOAK_URL}" \
      --realm master \
      --user "${ADMIN_USER}" \
      --password "${ADMIN_PASS}" > /dev/null 2>&1; then
      ready=1
      break
    fi
  fi
  sleep 1
done

if [ "${ready}" -ne 1 ]; then
  echo "keycloak-init: Keycloak not ready for admin login" >&2
  exit 1
fi

./opt/keycloak/bin/kcadm.sh update realms/master -s sslRequired=none > /dev/null
./opt/keycloak/bin/kcadm.sh update realms/autonoma -s sslRequired=none > /dev/null

echo "keycloak-init: sslRequired set to none for master/autonoma"
