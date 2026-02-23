from __future__ import annotations

from dataclasses import dataclass

_DESTRUCTIVE_KEYWORDS = (
    "delete",
    "drop",
    "destroy",
    "shutdown",
    "terminate",
    "wipe",
    "disable",
    "revoke",
)

_INJECTION_KEYWORDS = ("ignore previous", "exfiltrate", "credential", "api key", "password")

_THRESHOLDS = {
    "dev": {"approve": 0.5, "deny": 0.2},
    "stage": {"approve": 0.7, "deny": 0.4},
    "prod": {"approve": 0.9, "deny": 0.7},
}


@dataclass
class AgentEvalResult:
    score: float
    verdict: str
    reasons: list[str]


def evaluate_agent_run(
    goal: str,
    environment: str,
    tools: list[str],
    documents: list[str],
) -> AgentEvalResult:
    score = 1.0
    reasons: list[str] = []
    lowered = goal.lower()

    if any(keyword in lowered for keyword in _DESTRUCTIVE_KEYWORDS):
        score -= 0.5
        reasons.append("destructive_intent")

    if environment == "prod":
        score -= 0.2
        reasons.append("prod_environment")

    if tools and any(tool != "plugin_gateway.invoke" for tool in tools):
        score -= 0.4
        reasons.append("unapproved_tool")

    for doc in documents:
        lowered_doc = doc.lower()
        if any(keyword in lowered_doc for keyword in _INJECTION_KEYWORDS):
            score -= 0.4
            reasons.append("prompt_injection_signal")
            break

    score = max(0.0, min(1.0, score))
    thresholds = _THRESHOLDS.get(environment, _THRESHOLDS["dev"])
    if score < thresholds["deny"]:
        verdict = "deny"
    elif score < thresholds["approve"]:
        verdict = "require_approval"
    else:
        verdict = "allow"

    return AgentEvalResult(score=score, verdict=verdict, reasons=reasons)
