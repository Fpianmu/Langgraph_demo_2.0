from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from threading import RLock, Thread
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse

try:
    from sse_starlette.sse import EventSourceResponse as _SseEventSourceResponse
except ModuleNotFoundError:
    _SseEventSourceResponse = None

try:
    from agent.graph import graph
except ModuleNotFoundError as exc:
    graph = None
    GRAPH_IMPORT_ERROR = exc
else:
    GRAPH_IMPORT_ERROR = None
from agent.api_storage import (
    artifact_manifest_payload,
    artifact_markdown_text,
    artifact_payload,
    knowledge_gaps_payload,
    learning_progress_payload,
    list_artifacts_payload,
    path_assignments_payload,
    profile_payload,
    profile_score_payload,
    recommendations_payload,
    simulation_embed_payload,
    simulation_submission_payload,
    read_storage_file_response,
    resource_difficulty_trace_payload,
    scores_payload,
    storage_file_url,
)
from agent.course_resources.stage_loader import load_course_stages
from agent.observability.runner import stream_graph_agent_events
from agent.observability.sse import format_sse_event
from agent.onboarding_api import register_onboarding_routes
from agent.storage_layout import resolve_storage_root
from agent.frontend_state import (
    load_frontend_workspace_state,
    save_frontend_workspace_state,
)
from agent.tools.profile_tools import apply_profile_update_suggestions
from agent.tools.learning_recommendation_tools import (
    load_learning_recommendations,
    refresh_learning_recommendations,
    recommendation_quiz_payload,
)
from agent.tools.learning_progress_control import evaluate_next_step_readiness
from agent.tools.quiz_grading_tools import (
    QuizQuestionNotFound,
    QuizSubmissionInvalid,
    grade_quiz_answer,
    grade_saved_quiz_answer,
    submit_quiz_answers,
)
from agent.tools.quiz_profile_sync_tools import sync_quiz_profile_evidence


@dataclass
class RunRecord:
    run_id: str
    payload: dict[str, Any]
    status: str = "created"
    cancel_requested: bool = False
    events: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None
    lock: RLock = field(default_factory=RLock, repr=False)


app = FastAPI(title="LangGraph Demo 2.0 Agent Events")
register_onboarding_routes(app)
RUNS: dict[str, RunRecord] = {}
REQUEST_RUNS: dict[str, str] = {}


@app.get("/api/agent/health")
def agent_health() -> dict[str, Any]:
    rag_config = _rag_health()
    return {
        "status": "ok" if graph is not None else "degraded",
        "service": "LangGraph Demo 2.0",
        "storage_root": str(resolve_storage_root(None)),
        "graph_available": graph is not None,
        "graph_error": str(GRAPH_IMPORT_ERROR) if GRAPH_IMPORT_ERROR else None,
        "model_configured": bool(_deepseek_api_key()),
        **rag_config,
    }


def _event_source_response(generator: Any) -> Any:
    if _SseEventSourceResponse is not None:
        return _SseEventSourceResponse(generator)

    async def encoded():
        async for event in generator:
            if isinstance(event, dict) and "data" in event:
                data = event["data"]
                if isinstance(data, dict):
                    yield format_sse_event(data)
                else:
                    yield f"data: {data}\n\n"
            else:
                yield format_sse_event(event)

    return StreamingResponse(encoded(), media_type="text/event-stream")


@app.post("/api/agent")
@app.post("/api/graph/runs")
@app.post("/api/runs")
def create_run(payload: dict[str, Any]) -> dict[str, str]:
    if graph is None:
        raise HTTPException(status_code=503, detail=f"graph unavailable: {GRAPH_IMPORT_ERROR}")
    request_id = str(payload.get("request_id") or "").strip()
    if request_id:
        existing_id = REQUEST_RUNS.get(request_id)
        existing = RUNS.get(existing_id or "")
        if existing is not None:
            return {"run_id": existing.run_id, "status": existing.status}
    run_id = f"run_{uuid4().hex[:12]}"
    RUNS[run_id] = RunRecord(run_id=run_id, payload=dict(payload))
    if request_id:
        REQUEST_RUNS[request_id] = run_id
    Thread(target=_execute_run, args=(run_id,), name=f"zlink-{run_id}", daemon=True).start()
    return {"run_id": run_id, "status": "created"}


@app.get("/api/graph/runs/{run_id}")
@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    record = RUNS.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    with record.lock:
        return {
            "run_id": record.run_id,
            "status": record.status,
            "event_count": len(record.events),
            "result_url": f"/api/graph/runs/{run_id}/result" if record.status == "completed" else None,
            "error": record.error,
        }


@app.get("/api/graph/runs/{run_id}/result")
@app.get("/api/runs/{run_id}/result")
def get_run_result(run_id: str) -> Any:
    record = RUNS.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    with record.lock:
        if record.status == "failed":
            raise HTTPException(status_code=500, detail=record.error or "graph run failed")
        if record.status == "cancelled":
            raise HTTPException(status_code=409, detail="graph run was cancelled")
        if record.status != "completed" or record.result is None:
            return JSONResponse(
                status_code=202,
                content={"run_id": run_id, "status": record.status},
            )
        result = dict(record.result)
        result["agent_trace"] = _agent_trace(record.events)
        return {"run_id": run_id, "status": "completed", "result": result}


@app.post("/api/graph/runs/{run_id}/cancel")
@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str) -> dict[str, str]:
    record = RUNS.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    record.cancel_requested = True
    record.status = "cancelled"
    return {"run_id": record.run_id, "status": record.status}


@app.get("/api/agents/runs/{run_id}/events")
@app.get("/api/graph/runs/{run_id}/events")
@app.get("/api/runs/{run_id}/events")
def stream_run_events(run_id: str, request: Request) -> Any:
    record = RUNS.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    async def generate():
        index = _event_index(request.headers.get("last-event-id"))
        while True:
            if await request.is_disconnected():
                return
            with record.lock:
                pending = list(record.events[index:])
                status = record.status
            for event in pending:
                index += 1
                yield {
                    "id": event["event_id"],
                    "event": event["event_type"],
                    "data": event,
                }
            if status in {"completed", "failed", "cancelled"} and not pending:
                return
            await asyncio.sleep(0.1)

    return _event_source_response(generate())


def _execute_run(run_id: str) -> None:
    record = RUNS[run_id]
    with record.lock:
        if record.status != "created":
            return
        record.status = "running"

    final_state: dict[str, Any] = {}

    def store_result(state: dict[str, Any]) -> None:
        nonlocal final_state
        final_state = dict(state)

    try:
        for event in stream_graph_agent_events(
            graph,
            record.payload,
            run_id=run_id,
            on_result=store_result,
        ):
            with record.lock:
                if record.cancel_requested:
                    record.status = "cancelled"
                    return
                record.events.append(event)
        with record.lock:
            record.result = _normalize_graph_result(final_state, record.payload, run_id)
            record.status = "completed"
    except Exception as exc:
        with record.lock:
            record.status = "failed"
            record.error = str(exc)
            failure = {
                "event_type": "run.failed",
                "event_id": f"evt_failed_{len(record.events) + 1:06d}",
                "run_id": run_id,
                "detail": str(exc),
            }
            record.events.append(failure)


def _normalize_graph_result(state: dict[str, Any], payload: dict[str, Any], run_id: str) -> dict[str, Any]:
    final_output = state.get("verified_output") or state.get("final_output") or state.get("personalized_output")
    final_materials = state.get("verified_materials") or state.get("final_materials") or {}
    if not final_output and isinstance(final_materials, dict) and len(final_materials) == 1:
        final_output = next(iter(final_materials.values()))
    status = "success"
    verification_decision = str(state.get("verification_decision") or "")
    if verification_decision in {"safe_reject", "safe_reject_node"} or state.get("safe_reject_reason"):
        status = "content_rejected"
    result = {
        "api_version": "v2",
        "request_id": str(state.get("request_id") or payload.get("request_id") or ""),
        "run_id": run_id,
        "status": status,
        "content_type": str(state.get("content_type") or payload.get("content_type") or "qa"),
        "task": str(state.get("task") or payload.get("task") or payload.get("raw_prompt") or ""),
        "final_output": final_output if isinstance(final_output, dict) else None,
        "final_materials": final_materials if isinstance(final_materials, dict) else {},
        "rag_package": state.get("rag_package") if isinstance(state.get("rag_package"), dict) else None,
        "check_report": state.get("verification_summary") if isinstance(state.get("verification_summary"), dict) else None,
        "safety_report": state.get("safety_report") if isinstance(state.get("safety_report"), dict) else None,
        "profile_update_suggestions": state.get("profile_update_suggestions") if isinstance(state.get("profile_update_suggestions"), dict) else {},
        "saved_outputs": state.get("saved_outputs") if isinstance(state.get("saved_outputs"), dict) else {},
        "qa_session_id": str(state.get("qa_session_id") or payload.get("qa_session_id") or "") or None,
        "error_type": "verification_rejected" if status == "content_rejected" else None,
        "retry_count": int(state.get("retry_count") or state.get("verification_rewrite_count") or 0),
    }
    for key in (
        "personalized_qa_output",
        "personalized_question_output",
        "personalized_lecture_output",
        "final_qa_output",
        "final_question_output",
        "final_lecture_output",
        "lecture_artifact_paths",
        "saved_lecture_artifact",
        "profile_update_result",
        "learning_recommendations",
    ):
        value = state.get(key)
        if value is not None:
            result[key] = value
    return jsonable_encoder(result)


def _agent_trace(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    trace = []
    for event in events:
        if event.get("event_type") != "agent.activity":
            continue
        trace.append(
            {
                "node": str(event.get("node_id") or event.get("agent_id") or "agent"),
                "status": "success",
                "summary": str(event.get("display_text") or event.get("detail") or ""),
            }
        )
    return trace


def _event_index(last_event_id: str | None) -> int:
    if not last_event_id:
        return 0
    try:
        return max(int(str(last_event_id).rsplit("_", 1)[-1]), 0)
    except ValueError:
        return 0


def _deepseek_api_key() -> str:
    import os

    return os.getenv("DEEPSEEK_API_KEY", "").strip()


def _rag_health() -> dict[str, Any]:
    try:
        from agent.rag.config import RagConfig

        config = RagConfig.from_env()
        source_ready = any(path.is_dir() for path in (config.source_dir, *config.additional_source_dirs))
        index_ready = (config.index_dir / "docstore.json").is_file()
        return {
            "rag_ready": source_ready or index_ready,
            "rag_source_ready": source_ready,
            "rag_index_ready": index_ready,
        }
    except Exception:
        return {"rag_ready": False, "rag_source_ready": False, "rag_index_ready": False}


@app.get("/api/storage/users/{user_id}/profile")
@app.get("/api/profile/{user_id}")
def get_profile(user_id: str, storage_root: str | None = None, display_name: str | None = None, background_type: str | None = None) -> dict[str, Any]:
    return profile_payload(
        user_id=user_id,
        storage_root=storage_root,
        display_name=display_name,
        background_type=background_type,
    )


@app.put("/api/storage/users/{user_id}/profile")
@app.put("/api/profile/{user_id}")
def update_profile(user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    storage_root = payload.get("storage_root")
    request_id = str(payload.get("request_id") or f"req_{uuid4().hex[:12]}")
    suggestions = payload.get("suggestions")
    if not isinstance(suggestions, dict):
        suggestions = {
            key: value
            for key, value in payload.items()
            if key not in {"storage_root", "request_id"}
        }
    return apply_profile_update_suggestions(
        user_id=user_id,
        request_id=request_id,
        suggestions=suggestions,
        storage_root=storage_root,
    )


@app.get("/api/frontend-state/{user_id}")
@app.get("/api/state/{user_id}")
def get_frontend_state(user_id: str, storage_root: str | None = None) -> dict[str, Any]:
    return load_frontend_workspace_state(user_id=user_id, storage_root=storage_root)


@app.put("/api/frontend-state/{user_id}")
@app.put("/api/state/{user_id}")
def update_frontend_state(user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return save_frontend_workspace_state(
        user_id=user_id,
        payload=payload,
        storage_root=payload.get("storage_root"),
    )


@app.get("/api/storage/users/{user_id}/learning-progress")
def get_learning_progress(user_id: str, storage_root: str | None = None) -> dict[str, Any]:
    return learning_progress_payload(user_id=user_id, storage_root=storage_root)


@app.get("/api/storage/users/{user_id}/knowledge-gaps")
def get_knowledge_gaps(user_id: str, storage_root: str | None = None) -> dict[str, Any]:
    return knowledge_gaps_payload(user_id=user_id, storage_root=storage_root)


@app.get("/api/storage/users/{user_id}/scores")
def get_scores(user_id: str, storage_root: str | None = None) -> dict[str, Any]:
    return scores_payload(user_id=user_id, storage_root=storage_root)


@app.get("/api/storage/users/{user_id}/profile-score")
@app.get("/api/profile/{user_id}/profile-score")
def get_profile_score(user_id: str, storage_root: str | None = None) -> dict[str, Any]:
    return profile_score_payload(user_id=user_id, storage_root=storage_root)


@app.get("/api/storage/users/{user_id}/difficulty-trace")
@app.get("/api/profile/{user_id}/difficulty-trace")
def get_resource_difficulty_trace(
    user_id: str,
    storage_root: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    return resource_difficulty_trace_payload(user_id=user_id, storage_root=storage_root, limit=limit)


@app.get("/api/storage/users/{user_id}/path-assignments")
def get_path_assignments(user_id: str, storage_root: str | None = None) -> dict[str, Any]:
    return path_assignments_payload(user_id=user_id, storage_root=storage_root)


@app.get("/api/courses/{course_id}/learning-path")
def get_course_learning_path(
    course_id: str,
    path_id: str | None = None,
) -> dict[str, Any]:
    """Return the ordered, backend-owned chapter tree for one learning path."""
    try:
        return load_course_stages(course_id, path_id=path_id)
    except (FileNotFoundError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@app.get("/api/storage/users/{user_id}/recommendations")
def get_recommendations(user_id: str, storage_root: str | None = None) -> dict[str, Any]:
    return recommendations_payload(user_id=user_id, storage_root=storage_root)


@app.get("/api/storage/users/{user_id}/artifacts")
def get_artifacts(user_id: str, storage_root: str | None = None) -> dict[str, Any]:
    return list_artifacts_payload(user_id=user_id, storage_root=storage_root)


@app.get("/api/storage/users/{user_id}/artifacts/{artifact_id}")
def get_artifact(user_id: str, artifact_id: str, storage_root: str | None = None) -> dict[str, Any]:
    return artifact_payload(user_id=user_id, artifact_id=artifact_id, storage_root=storage_root)


@app.get("/api/storage/users/{user_id}/artifacts/{artifact_id}/manifest")
def get_artifact_manifest(user_id: str, artifact_id: str, storage_root: str | None = None) -> dict[str, Any]:
    return artifact_manifest_payload(user_id=user_id, artifact_id=artifact_id, storage_root=storage_root)


@app.get("/api/storage/users/{user_id}/artifacts/{artifact_id}/markdown")
def get_artifact_markdown(user_id: str, artifact_id: str, storage_root: str | None = None) -> Any:
    try:
        content = artifact_markdown_text(user_id=user_id, artifact_id=artifact_id, storage_root=storage_root)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="artifact markdown not found") from None
    return StreamingResponse(iter([content.encode("utf-8")]), media_type="text/markdown; charset=utf-8")


@app.get("/api/storage/files/{storage_path:path}/download")
def download_storage_file(
    storage_path: str,
    request: Request,
    storage_root: str | None = None,
) -> Any:
    try:
        return read_storage_file_response(
            storage_root=storage_root,
            storage_path=storage_path,
            request=request,
            download=True,
        )
    except ValueError:
        raise HTTPException(status_code=422, detail="path escapes doc") from None
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="file not found") from None


@app.get("/api/storage/files/{storage_path:path}")
def preview_storage_file(
    storage_path: str,
    request: Request,
    storage_root: str | None = None,
) -> Any:
    try:
        return read_storage_file_response(
            storage_root=storage_root,
            storage_path=storage_path,
            request=request,
            download=False,
        )
    except ValueError:
        raise HTTPException(status_code=422, detail="path escapes doc") from None
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="file not found") from None


@app.post("/agent/quiz/grade")
def grade_quiz_answer_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
    return _grade_quiz_payload(payload)


@app.post("/api/quiz-grade")
def grade_quiz_answer_compat_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
    return _grade_quiz_payload(payload)


@app.post("/agent/quiz/submit")
def submit_quiz_answers_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
    return _submit_quiz_payload(payload)


@app.post("/api/quiz-submit")
def submit_quiz_answers_compat_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
    return _submit_quiz_payload(payload)


@app.post("/api/storage/users/{user_id}/quiz-evidence")
def sync_quiz_profile_evidence_endpoint(
    user_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    evidence = payload.get("capability_evidence")
    if not isinstance(evidence, list) or not evidence:
        raise HTTPException(status_code=400, detail="capability_evidence is required")
    request_id = str(payload.get("request_id") or f"quiz_sync_{uuid4().hex[:12]}")
    try:
        return sync_quiz_profile_evidence(
            user_id=user_id,
            course_id=str(payload.get("course_id") or "cnc_lathe"),
            evidence=[item for item in evidence if isinstance(item, dict)],
            request_id=request_id,
            storage_root=payload.get("storage_root"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@app.get("/api/users/{user_id}/learning-recommendations")
def get_learning_recommendations_endpoint(
    user_id: str,
    storage_root: str | None = None,
) -> dict[str, Any]:
    return load_learning_recommendations(user_id=user_id, storage_root=storage_root)


@app.post("/api/users/{user_id}/learning-recommendations/{recommendation_id}/quiz")
def create_recommendation_quiz_run_endpoint(
    user_id: str,
    recommendation_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    try:
        run_payload = recommendation_quiz_payload(
            user_id=user_id,
            recommendation_id=recommendation_id,
            course_id=str(payload.get("course_id") or "cnc_lathe"),
            chapter_id=str(payload.get("chapter_id") or ""),
            question_count=int(payload.get("question_count") or 5),
            storage_root=payload.get("storage_root"),
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="recommendation not found") from None
    run_id = f"run_{uuid4().hex[:12]}"
    RUNS[run_id] = RunRecord(run_id=run_id, payload=run_payload)
    return {
        "run_id": run_id,
        "status": "created",
        "recommendation_id": recommendation_id,
    }


@app.post("/api/learning/next-step/evaluate")
@app.post("/api/tools/learning-path/evaluate")
def evaluate_next_step_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
    result = _evaluate_next_step_payload(payload)
    if result.get("can_advance") and payload.get("auto_start_run"):
        run_payload = dict(result["next_command"])
        if payload.get("storage_root"):
            run_payload["_storage_root"] = payload.get("storage_root")
        run_id = f"run_{uuid4().hex[:12]}"
        RUNS[run_id] = RunRecord(run_id=run_id, payload=run_payload)
        result["run_id"] = run_id
        result["run_status"] = "created"
    return result


@app.post("/api/tools/recommendation/generate")
def generate_learning_recommendations_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
    user_id = str(payload.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    storage_root = payload.get("storage_root")
    if bool(payload.get("refresh", True)):
        refreshed = refresh_learning_recommendations(user_id=user_id, storage_root=storage_root)
        payload = recommendations_payload(user_id=user_id, storage_root=storage_root)
        if isinstance(refreshed, dict) and refreshed.get("files"):
            payload["files"] = refreshed["files"]
        if not payload.get("recommendation_urls") and isinstance(payload.get("files"), dict):
            markdown_path = payload["files"].get("markdown")
            if markdown_path:
                payload["recommendation_urls"] = [storage_file_url(markdown_path)]
        return payload
    payload = recommendations_payload(user_id=user_id, storage_root=storage_root)
    if not payload.get("recommendation_urls") and isinstance(payload.get("files"), dict):
        markdown_path = payload["files"].get("markdown")
        if markdown_path:
            payload["recommendation_urls"] = [storage_file_url(markdown_path)]
    return payload


@app.post("/api/tools/quiz/grade")
def grade_quiz_tool_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
    return _grade_quiz_payload(payload)


@app.post("/api/tools/quiz/submit")
def submit_quiz_tool_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
    return _submit_quiz_payload(payload)


@app.get("/api/simulation/embed/{task_id}")
def get_cnc_simulation_embed_endpoint(
    task_id: str,
    user_id: str = "",
    course_id: str = "cnc_lathe",
    chapter_id: str = "4.1",
    storage_root: str | None = None,
    simulator_url: str | None = None,
    api_base_url: str | None = None,
) -> dict[str, Any]:
    return simulation_embed_payload(
        task_id=task_id,
        user_id=user_id,
        course_id=course_id,
        chapter_id=chapter_id,
        storage_root=storage_root,
        simulator_url=simulator_url,
        api_base_url=api_base_url,
    )


@app.post("/api/simulation/{task_id}/submissions")
def create_cnc_simulation_submission_endpoint(task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from agent.tools.cnc_simulation_tools import create_cnc_simulation_submission

    course_id = str(payload.get("course_id") or "cnc_lathe")
    chapter_id = str(payload.get("chapter_id") or "4.1")
    user_id = str(payload.get("user_id") or "").strip()
    source_code = str(payload.get("source_code") or payload.get("hnc_code") or "").strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    if not source_code:
        raise HTTPException(status_code=400, detail="source_code is required")
    try:
        return create_cnc_simulation_submission(
            user_id=user_id,
            course_id=course_id,
            chapter_id=chapter_id,
            task_id=task_id,
            source_code=source_code if source_code.endswith("\n") else source_code + "\n",
            submission_id=payload.get("submission_id"),
            request_id=str(payload.get("request_id") or ""),
            input_mode=str(payload.get("input_mode") or "editor"),
            original_filename=str(payload.get("original_filename") or "main.nc"),
            resource_root=payload.get("resource_root") or payload.get("_course_resource_root"),
            storage_root=payload.get("storage_root"),
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except KeyError:
        raise HTTPException(status_code=404, detail="simulation task not found") from None


@app.get("/api/simulation/{task_id}/submissions/{submission_id}")
def get_cnc_simulation_submission_endpoint(
    task_id: str,
    submission_id: str,
    user_id: str = "",
    course_id: str = "cnc_lathe",
    chapter_id: str = "4.1",
    storage_root: str | None = None,
) -> dict[str, Any]:
    if not str(user_id or "").strip():
        raise HTTPException(status_code=400, detail="user_id is required")
    try:
        return simulation_submission_payload(
            user_id=user_id,
            course_id=course_id,
            chapter_id=chapter_id,
            task_id=task_id,
            submission_id=submission_id,
            storage_root=storage_root,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="simulation submission not found") from None


def _grade_quiz_payload(payload: dict[str, Any]) -> dict[str, Any]:
    user_id = str(payload.get("user_id") or "").strip()
    artifact_id = str(payload.get("artifact_id") or "").strip()
    question_id = str(payload.get("question_id") or "").strip()
    question = payload.get("question")
    direct_question_payload = isinstance(question, dict) or any(
        key in payload for key in ("question_type", "reference_answer", "answer_aliases", "scoring_rubric", "correct_answer", "answer")
    )
    if direct_question_payload:
        return grade_quiz_answer(payload)
    if not user_id or not artifact_id or not question_id:
        raise HTTPException(status_code=400, detail="user_id, artifact_id and question_id are required")
    try:
        return grade_saved_quiz_answer(
            user_id=user_id,
            artifact_id=artifact_id,
            question_id=question_id,
            user_answer=payload.get("user_answer"),
            storage_root=payload.get("storage_root"),
        )
    except QuizQuestionNotFound:
        raise HTTPException(status_code=404, detail="question not found") from None


def _submit_quiz_payload(payload: dict[str, Any]) -> dict[str, Any]:
    user_id = str(payload.get("user_id") or "").strip()
    artifact_id = str(payload.get("artifact_id") or "").strip()
    answers = payload.get("answers")
    if not user_id or not artifact_id or not isinstance(answers, list):
        raise HTTPException(status_code=400, detail="user_id, artifact_id and answers are required")
    try:
        return submit_quiz_answers(
            user_id=user_id,
            artifact_id=artifact_id,
            course_id=str(payload.get("course_id") or ""),
            chapter_id=str(payload.get("chapter_id") or ""),
            answers=[item for item in answers if isinstance(item, dict)],
            storage_root=payload.get("storage_root"),
        )
    except QuizSubmissionInvalid as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except QuizQuestionNotFound:
        raise HTTPException(status_code=404, detail="question not found") from None


def _evaluate_next_step_payload(payload: dict[str, Any]) -> dict[str, Any]:
    user_id = str(payload.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    result = evaluate_next_step_readiness(
        user_id=user_id,
        course_id=str(payload.get("course_id") or "cnc_lathe"),
        chapter_id=str(payload.get("chapter_id") or "").strip() or None,
        force=bool(payload.get("force")),
        force_reason=str(payload.get("force_reason") or ""),
        storage_root=payload.get("storage_root"),
    )
    return result
