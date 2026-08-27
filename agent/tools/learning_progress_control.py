from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from agent.storage_layout import resolve_storage_root, safe_segment


CHAPTER_REQUIRED_TASKS: dict[str, list[str]] = {
    "1": ["quiz", "lecture"],
    "2": ["quiz", "lecture"],
    "3": ["quiz", "lecture"],
    "4": ["quiz", "lecture", "practice_material"],
    "5": ["practice_material", "quiz"],
}

QUIZ_PASS_RATE = 0.8


def evaluate_next_step_readiness(
    *,
    user_id: str,
    course_id: str = "cnc_lathe",
    chapter_id: str | None = None,
    force: bool = False,
    force_reason: str = "",
    storage_root: str | Path | None = None,
    quiz_pass_rate: float = QUIZ_PASS_RATE,
) -> dict[str, Any]:
    root = resolve_storage_root(storage_root)
    resolved_chapter_id = _resolve_chapter_id(root, user_id=user_id, course_id=course_id, chapter_id=chapter_id)
    chapter_group = _chapter_group(resolved_chapter_id)
    required_tasks = CHAPTER_REQUIRED_TASKS.get(chapter_group, [])
    task_results = [
        _evaluate_task(
            root,
            user_id=user_id,
            course_id=course_id,
            chapter_id=resolved_chapter_id,
            task_type=task_type,
            quiz_pass_rate=quiz_pass_rate,
        )
        for task_type in required_tasks
    ]
    completed_tasks = [item["type"] for item in task_results if item["passed"]]
    blockers = [_blocker_from_result(item) for item in task_results if not item["passed"]]
    passed = not blockers
    can_advance = passed or force
    status = "passed" if passed else "force_passed" if force else "blocked"
    result: dict[str, Any] = {
        "user_id": user_id,
        "course_id": course_id,
        "chapter_id": resolved_chapter_id,
        "chapter_group": chapter_group,
        "can_advance": can_advance,
        "status": status,
        "required_tasks": required_tasks,
        "completed_tasks": completed_tasks,
        "task_results": task_results,
        "blockers": blockers,
    }
    if force:
        result["force_reason"] = force_reason
    if can_advance:
        result["next_command"] = {
            "user_id": user_id,
            "course_id": course_id,
            "chapter_id": resolved_chapter_id,
            "content_type": "next_step",
            "learning_status_intent": "next_step",
        }
    return result


def _evaluate_task(
    root: Path,
    *,
    user_id: str,
    course_id: str,
    chapter_id: str,
    task_type: str,
    quiz_pass_rate: float,
) -> dict[str, Any]:
    if task_type == "quiz":
        return _evaluate_quiz(root, user_id=user_id, course_id=course_id, chapter_id=chapter_id, pass_rate=quiz_pass_rate)
    if task_type == "lecture":
        return _artifact_task_result(
            root,
            user_id=user_id,
            course_id=course_id,
            chapter_id=chapter_id,
            task_type=task_type,
            artifact_types={"lecture"},
            missing_message="本章讲义尚未生成或不可访问",
        )
    if task_type == "practice_material":
        return _artifact_task_result(
            root,
            user_id=user_id,
            course_id=course_id,
            chapter_id=chapter_id,
            task_type=task_type,
            artifact_types={"practice", "practice_guide"},
            missing_message="本章实训资料尚未生成或不可访问",
        )
    return {"type": task_type, "passed": False, "message": "未知任务类型"}


def _evaluate_quiz(root: Path, *, user_id: str, course_id: str, chapter_id: str, pass_rate: float) -> dict[str, Any]:
    quiz_artifacts = _matching_artifacts(
        root,
        user_id=user_id,
        course_id=course_id,
        chapter_id=chapter_id,
        artifact_types={"quiz"},
    )
    if not quiz_artifacts:
        return {"type": "quiz", "passed": False, "message": "本章题目尚未生成"}

    latest_attempt = _latest_quiz_attempt(root, user_id=user_id, quiz_artifacts=quiz_artifacts)
    if latest_attempt is None:
        return {
            "type": "quiz",
            "passed": False,
            "message": "本章题目尚未提交",
            "artifact_ids": [item["artifact_id"] for item in quiz_artifacts],
        }

    accuracy = _attempt_accuracy(root, user_id=user_id, attempt=latest_attempt)
    passed = accuracy >= pass_rate
    return {
        "type": "quiz",
        "passed": passed,
        "message": "章节测验已达标" if passed else "章节测验未达到通过线",
        "artifact_id": latest_attempt["artifact_id"],
        "attempt_id": latest_attempt["attempt_id"],
        "score_rate": round(accuracy, 4),
        "required_score_rate": pass_rate,
    }


def _artifact_task_result(
    root: Path,
    *,
    user_id: str,
    course_id: str,
    chapter_id: str,
    task_type: str,
    artifact_types: set[str],
    missing_message: str,
) -> dict[str, Any]:
    artifacts = _matching_artifacts(
        root,
        user_id=user_id,
        course_id=course_id,
        chapter_id=chapter_id,
        artifact_types=artifact_types,
    )
    available = [item for item in artifacts if _artifact_file_available(root, item)]
    if not available:
        return {"type": task_type, "passed": False, "message": missing_message}
    return {
        "type": task_type,
        "passed": True,
        "message": "任务已完成",
        "artifact_id": available[0]["artifact_id"],
    }


def _matching_artifacts(
    root: Path,
    *,
    user_id: str,
    course_id: str,
    chapter_id: str,
    artifact_types: set[str],
) -> list[dict[str, Any]]:
    db_path = root / "app.db"
    if not db_path.exists():
        return []
    placeholders = ",".join("?" for _ in artifact_types)
    params: list[Any] = [user_id, course_id, *sorted(artifact_types)]
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT artifact_id, artifact_type, title, course_id, chapter_id, markdown_path, metadata_json, created_at
            FROM generated_artifacts
            WHERE user_id = ? AND course_id = ? AND artifact_type IN ({placeholders})
            ORDER BY created_at DESC
            """,
            params,
        ).fetchall()
    wanted_group = _chapter_group(chapter_id)
    return [dict(row) for row in rows if _chapter_group(str(row["chapter_id"] or "")) == wanted_group]


def _latest_quiz_attempt(root: Path, *, user_id: str, quiz_artifacts: list[dict[str, Any]]) -> dict[str, Any] | None:
    db_path = root / "app.db"
    artifact_ids = [str(item["artifact_id"]) for item in quiz_artifacts if str(item.get("artifact_id") or "")]
    if not db_path.exists() or not artifact_ids:
        return None
    placeholders = ",".join("?" for _ in artifact_ids)
    params: list[Any] = [user_id, *artifact_ids]
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            f"""
            SELECT attempt_id, artifact_id, user_id, score, submitted_at
            FROM quiz_attempts
            WHERE user_id = ? AND artifact_id IN ({placeholders})
            ORDER BY submitted_at DESC
            LIMIT 1
            """,
            params,
        ).fetchone()
    return dict(row) if row is not None else None


def _attempt_accuracy(root: Path, *, user_id: str, attempt: dict[str, Any]) -> float:
    attempt_path = _find_attempt_file(root, user_id=user_id, artifact_id=str(attempt["artifact_id"]), attempt_id=str(attempt["attempt_id"]))
    if attempt_path is not None:
        try:
            data = json.loads(attempt_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        if isinstance(data, dict):
            for key in ("accuracy", "score_rate"):
                value = _float_or_none(data.get(key))
                if value is not None:
                    return _clamp_unit(value)
            score = _float_or_none(data.get("score"))
            possible = _float_or_none(data.get("total_possible"))
            if score is not None and possible and possible > 0:
                return _clamp_unit(score / possible)
    score = _float_or_none(attempt.get("score"))
    return 1.0 if score and score > 0 else 0.0


def _find_attempt_file(root: Path, *, user_id: str, artifact_id: str, attempt_id: str) -> Path | None:
    user_questions = root / "users" / safe_segment(user_id) / "questions"
    if not user_questions.exists():
        return None
    for path in user_questions.rglob(f"{safe_segment(attempt_id)}.json"):
        if safe_segment(artifact_id) in path.parts:
            return path
    return None


def _artifact_file_available(root: Path, artifact: dict[str, Any]) -> bool:
    markdown_path = str(artifact.get("markdown_path") or "").strip()
    if not markdown_path:
        return True
    return (root / markdown_path).exists()


def _resolve_chapter_id(root: Path, *, user_id: str, course_id: str, chapter_id: str | None) -> str:
    explicit = str(chapter_id or "").strip()
    if explicit:
        return explicit
    db_path = root / "app.db"
    if db_path.exists():
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT chapter_id
                FROM learning_progress
                WHERE user_id = ? AND course_id = ?
                ORDER BY
                    CASE status
                        WHEN 'in_progress' THEN 0
                        WHEN 'needs_review' THEN 1
                        WHEN 'learning' THEN 2
                        ELSE 3
                    END,
                    updated_at DESC
                LIMIT 1
                """,
                (user_id, course_id),
            ).fetchone()
        if row is not None and str(row["chapter_id"] or "").strip():
            return str(row["chapter_id"]).strip()
    return "1"


def _blocker_from_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in result.items()
        if key not in {"passed"} and value is not None and value != ""
    }


def _chapter_group(chapter_id: str) -> str:
    text = str(chapter_id or "").strip()
    if not text:
        return ""
    return text.split(".", 1)[0]


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp_unit(value: float) -> float:
    return min(max(float(value), 0.0), 1.0)
