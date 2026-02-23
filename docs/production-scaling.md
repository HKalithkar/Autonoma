# Production Scaling Guide

## Overview
Autonoma services are stateless (API, agent-runtime, plugin-gateway, web) and can
scale horizontally. Stateful dependencies (Postgres/Redis/vector DB) should use
managed services or dedicated HA clusters.

## Kubernetes manifests
Starter manifests are in `infra/k8s/base/`:
- Deployments + Services for API, agent-runtime, plugin-gateway, web, policy
- HPAs for API, agent-runtime, plugin-gateway

These manifests are intentionally minimal and should be adapted to your cluster,
image registry, and secrets management.

## Scaling recommendations
- API:
  - HPA: 2–10 replicas
  - Requests: 250m CPU / 256Mi
  - Limits: 1 CPU / 1Gi
- Agent runtime:
  - HPA: 2–20 replicas (burst for load)
  - Requests: 500m CPU / 512Mi
  - Limits: 2 CPU / 2Gi
- Plugin gateway:
  - HPA: 2–10 replicas
  - Requests: 200m CPU / 256Mi
  - Limits: 1 CPU / 1Gi

## Reliability
- Use a managed Postgres with HA.
- Redis should be clustered for session/memory state.
- Vector DB should be provisioned with HA (Weaviate/Qdrant).

## Security
- Use workload identity or mTLS for service-to-service auth.
- Store secrets in a dedicated secret manager; only references should be stored
  in the API database.
