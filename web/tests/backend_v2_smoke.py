"""Offline smoke test for the v2 create/events/result HTTP contract."""

from __future__ import annotations

import time
from typing import Any, Iterator

from fastapi.testclient import TestClient

import agent.api as api


class FakeGraph:
    def stream(
        self,
        initial_state: dict[str, Any],
        *,
        stream_mode: list[str],
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        assert stream_mode == ["updates", "values"]
        yield "updates", {"input_router": {"input_route": "qa"}}
        final_state = {
            **initial_state,
            "task": initial_state.get("raw_prompt", ""),
            "final_output": {
                "title": "离线验收",
                "summary": "第二版接口链路可用。",
                "payload": {
                    "question": initial_state.get("raw_prompt", ""),
                    "answer": "模拟回答",
                },
            },
        }
        yield "values", final_state


def main() -> None:
    original_graph = api.graph
    api.graph = FakeGraph()
    api.RUNS.clear()
    api.REQUEST_RUNS.clear()
    try:
        client = TestClient(api.app)
        created = client.post(
            "/api/graph/runs",
            json={
                "request_id": "offline-v2-smoke",
                "user_id": "smoke-user",
                "content_type": "qa",
                "raw_prompt": "验收第二版后端",
                "learner_profile": {"level": "beginner"},
                "latest_scores": {"safety": 42},
                "learning_progress": {"currentStageId": "entry"},
            },
        )
        created.raise_for_status()
        run_id = created.json()["run_id"]

        for _ in range(100):
            status = client.get(f"/api/graph/runs/{run_id}").json()["status"]
            if status in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.01)
        assert status == "completed", status

        with client.stream("GET", f"/api/graph/runs/{run_id}/events") as response:
            response.raise_for_status()
            event_text = "".join(response.iter_text())
        assert "run.started" in event_text
        assert "agent.activity" in event_text
        assert "run.completed" in event_text

        result_response = client.get(f"/api/graph/runs/{run_id}/result")
        result_response.raise_for_status()
        result = result_response.json()["result"]
        assert result["api_version"] == "v2"
        assert result["final_output"]["payload"]["answer"] == "模拟回答"
        assert result["agent_trace"]
        print("v2 create/events/result smoke test passed")
    finally:
        api.graph = original_graph
        api.RUNS.clear()
        api.REQUEST_RUNS.clear()


if __name__ == "__main__":
    main()
