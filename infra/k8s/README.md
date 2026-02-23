# Kubernetes starter manifests

These manifests are a minimal starting point for production scaling. They are
not a full production deployment. Replace image references, secrets, and config
for your environment.

## Apply order
1) Create namespace (optional)
2) Apply config + secrets:
   - `infra/k8s/base/configmap.yaml`
   - `infra/k8s/base/secret.example.yaml` (replace with a real Secret)
3) Apply services/deployments/HPAs:
   - `infra/k8s/base/api.yaml`
   - `infra/k8s/base/agent-runtime.yaml`
   - `infra/k8s/base/plugin-gateway.yaml`
   - `infra/k8s/base/web.yaml`
   - `infra/k8s/base/policy.yaml`

## Notes
- Postgres/Redis/Vector DB are expected to be managed services.
- Replace the `autonoma-policy` ConfigMap with the real `apps/policy/policy.rego`.
- Configure `VITE_API_URL` in `infra/k8s/base/web.yaml` to your API endpoint.
