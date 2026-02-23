---
name: autonoma-agent-evals-safety
description: Implement runtime + scheduled evaluation of agent behavior (safety, policy alignment, reliability), score-based gating, and automatic HITL escalation.
---

# Agent Evaluation & Safety Module

## Goals
- Evaluate agent actions:
  - safety (risk, destructive intent)
  - policy alignment
  - correctness (expected schema, valid targets)
  - reliability (repeat failures, timeouts)
- Produce score per action/run and per agent.

## Runtime hooks
- After each plan step:
  - compute eval score
  - if below threshold → force HITL or block
- Store eval metadata with audit + workflow run.

## Scheduled tests
- Replay incident simulations and adversarial prompts.
- Regression suite for prompt injection attempts.

## Deliverables
- Evaluation engine (rules + optional LLM-as-judge with strict guardrails)
- Score thresholds per environment
- Dashboards for agent scores
- CI job to run eval regression tests

## Review checklist
- No eval system can override policy allow/deny (policy is final)
- Deterministic baseline checks always on
- Clear operator visibility into why a score was low
