from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agent.observability.registry import activity_for_node, agent_for_node


SENSITIVE_KEYS = {
    "raw_prompt",
    "task_draft",
    "llm_raw_output",
    "rag_llm_raw_output",
    "feedback_llm_raw_output",
    "progress_personalization_raw_output",
    "progress_quiz_generation_raw_output",
    "verification_query_planner_raw_output",
    "profile_md_content",
    "profile_context",
    "progress_profile_context",
    "knowledge_gap_documents",
    "knowledge_gap_events",
    "final_output",
    "final_materials",
    "generated_content",
    "generated_materials",
    "personalized_output",
    "personalized_materials",
}


def sanitize_payload_refs(value: Any) -> Any:
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, nested_value in value.items():
            if str(key) in SENSITIVE_KEYS or str(key).startswith("_"):
                continue
            safe[str(key)] = sanitize_payload_refs(nested_value)
        return safe
    if isinstance(value, list):
        return [sanitize_payload_refs(item) for item in value[:20]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        text = str(value)
        if isinstance(value, str) and len(text) > 160:
            return f"{text[:157]}..."
        return value
    return str(type(value).__name__)


class AgentEventFactory:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self._counter = 0

    def _event_id(self) -> str:
        self._counter += 1
        return f"evt_{self._counter:06d}"

    def _base(self, event_type: str) -> dict[str, Any]:
        return {
            "event_type": event_type,
            "event_id": self._event_id(),
            "run_id": self.run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def run_started(self) -> dict[str, Any]:
        return self._base("run.started")

    def run_completed(self) -> dict[str, Any]:
        return self._base("run.completed")

    def agent_activity(
        self,
        *,
        node_id: str,
        detail: str | None = None,
        payload_refs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        agent = agent_for_node(node_id)
        event = self._base("agent.activity")
        event.update(
            {
                "agent_id": agent.agent_id,
                "agent_display_name": agent.display_name,
                "node_id": node_id,
                "display_text": activity_for_node(node_id),
                "detail": detail or activity_for_node(node_id),
                "payload_refs": sanitize_payload_refs(payload_refs or {}),
            }
        )
        return event

    def agent_message(
        self,
        *,
        from_agent: str,
        to_agent: str,
        display_text: str,
        message_type: str,
        detail: str = "",
        payload_refs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = self._base("agent.message")
        event.update(
            {
                "from_agent": from_agent,
                "to_agent": to_agent,
                "message_type": message_type,
                "display_text": display_text,
                "detail": detail,
                "payload_refs": sanitize_payload_refs(payload_refs or {}),
            }
        )
        return event
