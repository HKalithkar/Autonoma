---
name: autonoma-gitops-engine
description: Implement GitOps execution flow: generate IaC changes, create PRs/commits, enforce approvals, trigger pipeline runs, and verify convergence with audit trails.
---

# GitOps Engine Integration

## Core flow
- Agent proposes change → represented as code (IaC/config)
- Create branch/commit + PR (or direct commit in dev)
- Policy check:
  - require PR approvals for prod/high-risk
- Trigger pipeline:
  - Argo CD/Flux reconcile OR CI pipeline runs Terraform/Helm
- Track status → update workflow run record

## Must-haves
- Strong linking:
  - workflow_run_id ↔ git commit SHA ↔ pipeline run id
- Rollback support:
  - revert commit or apply previous desired state
- Verification step:
  - post-apply checks via Plugin Gateway (read-only queries)

## Deliverables
- Git provider abstraction (GitHub/GitLab)
- GitOps change generator interface (templates + safe rendering)
- Status tracker + persistence
- Integration tests with a local git repo fixture
