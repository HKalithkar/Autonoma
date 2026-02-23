#!/bin/sh
set -eu

SEED_DIR="/seed/workflows"
MARKER_FILE="/home/node/.n8n/.autonoma_seeded_v1"
N8N_LOCAL_URL="${N8N_LOCAL_URL:-http://127.0.0.1:${N8N_PORT:-5678}}"
N8N_PRESET_OWNER_EMAIL="${N8N_PRESET_OWNER_EMAIL:-admin@n8n.local}"
N8N_PRESET_OWNER_PASSWORD="${N8N_PRESET_OWNER_PASSWORD:-AutonomaN8nDev1}"
N8N_PRESET_OWNER_FIRST_NAME="${N8N_PRESET_OWNER_FIRST_NAME:-Autonoma}"
N8N_PRESET_OWNER_LAST_NAME="${N8N_PRESET_OWNER_LAST_NAME:-Admin}"

activate_seeded_workflows() {
  export_file="/tmp/autonoma-workflows-export.json"
  n8n export:workflow --all --output="${export_file}" >/dev/null

  for workflow_name in \
    "autonoma-n8n-health-check" \
    "autonoma-n8n-cache-refresh" \
    "autonoma-n8n-index-rebuild" \
    "autonoma-n8n-cost-report"
  do
    workflow_id="$(
      node -e '
        const fs = require("fs");
        const workflowName = process.argv[1];
        const exportFile = process.argv[2];
        const parsed = JSON.parse(fs.readFileSync(exportFile, "utf8"));
        const workflows = Array.isArray(parsed) ? parsed : (parsed.data || []);
        const match = workflows.find((wf) => wf.name === workflowName);
        if (match && match.id !== undefined && match.id !== null) {
          process.stdout.write(String(match.id));
        }
      ' "${workflow_name}" "${export_file}"
    )"

    if [ -n "${workflow_id}" ]; then
      n8n update:workflow --id="${workflow_id}" --active=true >/dev/null
    fi
  done

  rm -f "${export_file}"
}

setup_preset_owner() {
  attempts=0
  while [ "${attempts}" -lt 40 ]; do
    if wget -qO- "${N8N_LOCAL_URL%/}/healthz" >/dev/null 2>&1; then
      break
    fi
    attempts=$((attempts + 1))
    sleep 1
  done

  node -e '
    const baseUrl = (process.env.N8N_LOCAL_URL || "http://127.0.0.1:5678").replace(/\/+$/, "");
    const endpoints = [`${baseUrl}/rest/owner/setup`, `${baseUrl}/owner/setup`];
    const payload = {
      email: process.env.N8N_PRESET_OWNER_EMAIL || "admin@n8n.local",
      password: process.env.N8N_PRESET_OWNER_PASSWORD || "AutonomaN8nDev1",
      firstName: process.env.N8N_PRESET_OWNER_FIRST_NAME || "Autonoma",
      lastName: process.env.N8N_PRESET_OWNER_LAST_NAME || "Admin",
    };

    (async () => {
      for (let attempt = 0; attempt < 60; attempt += 1) {
        for (const endpoint of endpoints) {
          try {
            const response = await fetch(endpoint, {
              method: "POST",
              headers: { "content-type": "application/json" },
              body: JSON.stringify(payload),
            });
            const bodyText = await response.text();
            if (response.ok || bodyText.includes("Instance owner already setup")) {
              process.exit(0);
            }
            if (response.status === 404 || response.status >= 500) {
              continue;
            }
            console.error(`n8n preset owner setup failed: status=${response.status}`);
            console.error(bodyText);
            process.exit(1);
          } catch (_error) {
            continue;
          }
        }
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
      console.error("n8n preset owner setup failed: owner setup endpoint not reachable");
      process.exit(1);
    })();
  '
}

if [ ! -f "${MARKER_FILE}" ]; then
  if [ -d "${SEED_DIR}" ]; then
    n8n import:workflow --separate --input="${SEED_DIR}"
  fi
  touch "${MARKER_FILE}"
fi

activate_seeded_workflows

n8n start &
N8N_PID=$!
setup_preset_owner
wait "${N8N_PID}"
