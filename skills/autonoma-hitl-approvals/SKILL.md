---
name: autonoma-hitl-approvals
description: Build Human-in-the-Loop approval gates: risk-based pausing, approval UI + API, separation of duties, and resumable workflows.
---

# HITL Approval Framework

## What to implement
- Approval object model:
  - requested_by, required_role, risk_level, rationale, plan summary, artifacts (diffs, logs)
- API:
  - list pending approvals
  - approve/reject (with comment)
- Enforcement:
  - policy decides when HITL is required
  - workflow pauses until decision

## Separation of duties
- Approver must not equal requester for protected actions.
- Track approver identity, time, decision, comment.

## UI requirements
- Simple approvals inbox
- Diff/plan view with “what will change” emphasis
- Audit trail link

## Deliverables
- Approval service + DB schema
- UI screens
- Unit + integration tests for pause/resume flows
