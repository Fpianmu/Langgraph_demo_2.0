from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

try:
    from sse_starlette.sse import EventSourceResponse as _SseEventSourceResponse
except ModuleNotFoundError:
    _SseEventSourceResponse = None

from agent.graph import graph
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
from agent.observability.runner import stream_graph_agent_events
from agent.observability.sse import format_sse_event
from agent.storage_layout import resolve_storage_root
from agent.tools.profile_tools import apply_profile_update_suggestions
from agent.tools.cnc_simulation_tools import create_cnc_simulation_submission
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


@dataclass
class RunRecord:
    run_id: str
    payload: dict[str, Any]
    status: str = "created"
    cancel_requested: bool = False
    events: list[dict[str, Any]] = field(default_factory=list)


app = FastAPI(title="LangGraph Demo 2.0 Agent Events")
RUNS: dict[str, RunRecord] = {}


@app.get("/api/agent/health")
def agent_health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "LangGraph Demo 2.0",
        "storage_root": str(resolve_storage_root(None)),
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
    run_id = f"run_{uuid4().hex[:12]}"
    RUNS[run_id] = RunRecord(run_id=run_id, payload=dict(payload))
    return {"run_id": run_id, "status": "created"}


@app.get("/api/graph/runs/{run_id}")
@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    record = RUNS.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {"run_id": record.run_id, "status": record.status, "event_count": len(record.events)}


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
def stream_run_events(run_id: str) -> Any:
    record = RUNS.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")

    async def generate():
        if record.status == "cancelled":
            return
        record.status = "running"
        try:
            for event in stream_graph_agent_events(graph, record.payload, run_id=run_id):
                if record.cancel_requested:
                    record.status = "cancelled"
                    return
                record.events.append(event)
                yield {
                    "id": event["event_id"],
                    "event": event["event_type"],
                    "data": event,
                }
            if record.status != "cancelled":
                record.status = "completed"
        except Exception as exc:
            record.status = "failed"
            failure = {
                "event_type": "run.failed",
                "event_id": f"evt_failed_{len(record.events) + 1:06d}",
                "run_id": run_id,
                "detail": str(exc),
            }
            record.events.append(failure)
            yield {"id": failure["event_id"], "event": failure["event_type"], "data": failure}

    return _event_source_response(generate())


@app.get("/api/storage/users/{user_id}/profile")
@app.get("/api/profile/{user_id}")
@app.get("/api/state/{user_id}")
def get_profile(user_id: str, storage_root: str | None = None, display_name: str | None = None, background_type: str | None = None) -> dict[str, Any]:
    return profile_payload(
        user_id=user_id,
        storage_root=storage_root,
        display_name=display_name,
        background_type=background_type,
    )


@app.put("/api/storage/users/{user_id}/profile")
@app.put("/api/profile/{user_id}")
@app.put("/api/state/{user_id}")
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
