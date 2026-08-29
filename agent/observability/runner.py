from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
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


def stream_graph_agent_events(
    compiled_graph: Any,
    initial_state: dict[str, Any],
    *,
    run_id: str,
    on_result: Callable[[dict[str, Any]], None] | None = None,
) -> Iterator[dict[str, Any]]:
    """Stream public activity events while retaining the final graph state.

    LangGraph can emit both node updates and complete state snapshots in one
    execution.  The previous implementation consumed only updates, which made
    it impossible for the HTTP layer to return the generated answer.
    """
    factory = AgentEventFactory(run_id)
    yield factory.run_started()
    previous_node: str | None = None
    final_state: dict[str, Any] = dict(initial_state)

    chunks = compiled_graph.stream(initial_state, stream_mode=["updates", "values"])
    for item in chunks:
        if not isinstance(item, tuple) or len(item) != 2:
            continue
        mode, chunk = item
        if mode == "values" and isinstance(chunk, dict):
            final_state = dict(chunk)
            continue
        if mode != "updates" or not isinstance(chunk, dict):
            continue
        for node_id, update in chunk.items():
            node_id = str(node_id)
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
                )
            payload_refs = update if isinstance(update, dict) else {}
            yield factory.agent_activity(node_id=node_id, payload_refs=payload_refs)
            previous_node = node_id

    if on_result is not None:
        on_result(final_state)
    yield factory.run_completed(result_url=f"/api/graph/runs/{run_id}/result")
