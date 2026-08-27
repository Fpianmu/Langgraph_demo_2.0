from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from agent.observability.events import AgentEventFactory
from agent.observability.handoffs import message_for_transition
from agent.observability.registry import NODE_AGENT_MAP


def events_from_node_sequence(
    run_id: str,
    node_ids: Iterable[str],
    *,
    payload_refs_by_node: dict[str, dict[str, Any]] | None = None,
) -> Iterator[dict[str, Any]]:
    factory = AgentEventFactory(run_id)
    yield factory.run_started()
    previous_node: str | None = None
    payload_refs_by_node = payload_refs_by_node or {}
    for node_id in node_ids:
        if node_id not in NODE_AGENT_MAP:
            previous_node = node_id
            continue
        handoff = message_for_transition(previous_node, node_id)
        if handoff:
            yield factory.agent_message(
                from_agent=handoff.from_agent,
                to_agent=handoff.to_agent,
                display_text=handoff.display_text,
                message_type=handoff.message_type,
                detail=handoff.detail,
                payload_refs=payload_refs_by_node.get(node_id, {}),
            )
        yield factory.agent_activity(node_id=node_id, payload_refs=payload_refs_by_node.get(node_id, {}))
        previous_node = node_id
    yield factory.run_completed()


def node_ids_from_langgraph_chunks(chunks: Iterable[Any]) -> Iterator[str]:
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        for key in chunk:
            if key in NODE_AGENT_MAP:
                yield str(key)


def stream_graph_agent_events(compiled_graph: Any, initial_state: dict[str, Any], *, run_id: str) -> Iterator[dict[str, Any]]:
    chunks = compiled_graph.stream(initial_state, stream_mode="updates")
    yield from events_from_node_sequence(run_id, node_ids_from_langgraph_chunks(chunks))
