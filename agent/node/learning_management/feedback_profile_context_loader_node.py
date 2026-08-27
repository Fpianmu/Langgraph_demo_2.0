from __future__ import annotations

from typing import Any

from agent.node.node_logging import log_node_runtime
from agent.state import OverallState
from agent.tools.profile_tools import load_profile_context


@log_node_runtime("feedback_profile_context_loader_node")
def feedback_profile_context_loader_node(state: OverallState) -> OverallState:
    user_id = str(state.get("user_id") or "").strip()
    if not user_id:
        return {
            "profile_context": state.get("profile_context") or {},
            "profile_context_load_result": {
                "status": "invalid",
                "reason": "missing_user_id",
            },
        }

    context = load_profile_context(
        user_id=user_id,
        display_name=_optional_text(state.get("display_name")),
        background_type=_optional_text(state.get("background_type")),
        storage_root=state.get("_storage_root"),
    )
    return {
        "profile_context": context,
        "profile_context_load_result": {
            "status": "success",
            "profile_md_ref": context.get("profile_md_ref"),
            "capability_evidence_count": (context.get("capability_assessment_summary") or {}).get("evidence_count", 0),
            "knowledge_gap_open_count": (context.get("knowledge_gap_summary") or {}).get("open_count", 0),
        },
    }


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
