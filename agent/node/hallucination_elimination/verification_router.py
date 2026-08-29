from __future__ import annotations

from typing import Literal

from langgraph.types import Command

from agent.node.node_logging import log_node_runtime
from agent.state import OverallState


MAX_RETRIEVAL_COUNT = 1
MAX_REWRITE_COUNT = 1

VerificationRoute = Literal[
    "verified_persistence_node",
    "verification_query_planner_node",
    "rewrite_node",
    "safe_reject_node",
]


@log_node_runtime("verification_router")
def verification_router(state: OverallState) -> Command[VerificationRoute]:
    checks = state.get("claim_checks") or []
    quiz_schema = state.get("quiz_schema_validation_result")
    if isinstance(quiz_schema, dict) and quiz_schema.get("status") != "success":
        route: VerificationRoute = "safe_reject_node"
    elif not checks:
        route: VerificationRoute = "safe_reject_node"
    elif all(item.get("label") == "supported" and item.get("evidence_refs") for item in checks):
        route = "verified_persistence_node"
    elif any(item.get("label") == "unsupported" for item in checks) and int(state.get("verification_retrieval_count") or 0) < MAX_RETRIEVAL_COUNT:
        route = "verification_query_planner_node"
    elif any(item.get("label") in {"partial", "conflict", "unsupported"} for item in checks) and int(state.get("verification_rewrite_count") or 0) < MAX_REWRITE_COUNT:
        route = "rewrite_node"
    elif _grounded_partial_qa_can_pass(state, checks):
        route = "verified_persistence_node"
    else:
        route = "safe_reject_node"
    return Command(
        update={
            "verification_decision": route,
            "verification_history": [
                *(state.get("verification_history") or []),
                {"node": "verification_router", "decision": route},
            ],
        },
        goto=route,
    )


def _grounded_partial_qa_can_pass(state: OverallState, checks: list[dict]) -> bool:
    content_type = str(state.get("content_type") or "").strip()
    if content_type not in {"qa", "qa_answer"}:
        return False

    labels = {str(item.get("label") or "") for item in checks}
    if labels - {"supported", "partial"}:
        return False

    return all(item.get("evidence_refs") for item in checks)
