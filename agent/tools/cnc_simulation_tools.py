from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent.course_resources.repository import CourseResourceRepository
from agent.storage_layout import ensure_within, resolve_storage_root, safe_segment, user_root


SIMULATION_ARTIFACTS = {
    "normalized_code.nc": "text",
    "semantic_program.json": "json",
    "cncjs_preview_result.json": "json",
    "raw_code_check_result.json": "json",
    "expected_result_check.json": "json",
    "merged_result.json": "json",
    "answer_snapshot.json": "json",
    "diagnosis.json": "json",
    "profile_evidence_packet.json": "json",
    "feedback.md": "text",
}


def load_cnc_exercise(
    course_id: str,
    chapter_id: str,
    task_id: str,
    *,
    resource_root: str | Path | None = None,
) -> dict[str, Any]:
    return CourseResourceRepository(resource_root).load_simulation_task_bundle(
        course_id,
        chapter_id,
        task_id,
    )


def load_cnc_simulation_rules(
    course_id: str,
    *,
    resource_root: str | Path | None = None,
) -> dict[str, dict[str, Any]]:
    return CourseResourceRepository(resource_root).load_simulation_rules(course_id)


def create_cnc_simulation_submission(
    *,
    user_id: str,
    course_id: str,
    chapter_id: str,
    task_id: str,
    source_code: str,
    submission_id: str | None = None,
    request_id: str = "",
    input_mode: str = "editor",
    original_filename: str = "main.nc",
    resource_root: str | Path | None = None,
    storage_root: str | Path | None = None,
) -> dict[str, str]:
    if not isinstance(source_code, str):
        raise TypeError("source_code must be a string")
    if not source_code.strip():
        raise ValueError("source_code must not be empty")

    exercise = load_cnc_exercise(
        course_id,
        chapter_id,
        task_id,
        resource_root=resource_root,
    )
    root = resolve_storage_root(storage_root)
    submission_id = safe_segment(submission_id or f"submission_{uuid4().hex[:12]}")
    task_folder = _simulation_task_folder(
        root,
        user_id=user_id,
        chapter_id=chapter_id,
        task_id=task_id,
    )
    submission_folder = ensure_within(root, task_folder / "submissions" / submission_id)
    submission_folder.mkdir(parents=True, exist_ok=True)
    source_path = ensure_within(submission_folder, submission_folder / "source_code.nc")
    source_path.write_text(source_code, encoding="utf-8")

    static_task_ref = _static_task_ref(exercise.get("task_manifest_path"), course_id)
    _write_json(
        task_folder / "manifest.json",
        {
            "source": "path_generated",
            "question_source": "course_resources",
            "course_id": course_id,
            "chapter_id": chapter_id,
            "task_id": task_id,
            "static_task_ref": static_task_ref,
            "submissions_path": _relative(root, task_folder / "submissions"),
        },
    )
    submission_path = submission_folder / "submission.json"
    _write_json(
        submission_path,
        {
            "submission_id": submission_id,
            "user_id": user_id,
            "request_id": request_id,
            "course_id": course_id,
            "chapter_id": chapter_id,
            "task_id": task_id,
            "input_mode": input_mode,
            "original_filename": original_filename,
            "source_code_path": "source_code.nc",
            "question_source": "course_resources",
            "static_task_ref": static_task_ref,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return {
        "submission_id": submission_id,
        "task_manifest": str((task_folder / "manifest.json").resolve()),
        "submission": str(submission_path.resolve()),
        "submission_folder": str(submission_folder.resolve()),
        "source_code": str(source_path.resolve()),
        "task_manifest_ref": _relative(root, task_folder / "manifest.json"),
        "submission_ref": _relative(root, submission_path),
        "source_code_ref": _relative(root, source_path),
        "static_task_ref": static_task_ref,
    }


def save_cnc_simulation_artifact(
    *,
    user_id: str,
    course_id: str,
    chapter_id: str,
    task_id: str,
    attempt_id: str,
    artifact_name: str,
    content: Any,
    storage_root: str | Path | None = None,
) -> dict[str, str]:
    artifact_type = SIMULATION_ARTIFACTS.get(artifact_name)
    if artifact_type is None:
        raise ValueError(f"unsupported CNC simulation artifact: {artifact_name}")

    root = resolve_storage_root(storage_root)
    submission_folder = ensure_within(
        root,
        _simulation_task_folder(
            root,
            user_id=user_id,
            chapter_id=chapter_id,
            task_id=task_id,
        )
        / "submissions"
        / safe_segment(attempt_id),
    )
    if not submission_folder.is_dir():
        raise FileNotFoundError(f"simulation submission does not exist: {attempt_id}")
    path = ensure_within(submission_folder, submission_folder / artifact_name)
    if artifact_type == "json":
        _write_json(path, content)
    else:
        if not isinstance(content, str):
            raise TypeError(f"{artifact_name} content must be a string")
        path.write_text(content, encoding="utf-8")
    return {
        "artifact_name": artifact_name,
        "path": str(path.resolve()),
        "relative_path": _relative(root, path),
    }


def _simulation_task_folder(root: Path, *, user_id: str, chapter_id: str, task_id: str) -> Path:
    return (
        user_root(root, user_id)
        / "questions"
        / "path_generated"
        / _chapter_group(chapter_id)
        / _chapter_segment(chapter_id)
        / f"simulation_{safe_segment(task_id)}"
    )


def _static_task_ref(task_manifest_path: Any, course_id: str) -> str:
    normalized = str(task_manifest_path or "").replace("\\", "/")
    marker = f"/course_resources/{course_id}/"
    if marker in normalized:
        return "course_resources/" + course_id + "/" + normalized.split(marker, 1)[1]
    return normalized


def _write_json(path: Path, content: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")


def _relative(root: Path, path: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")


def _chapter_segment(chapter_id: str) -> str:
    segment = "".join(char if char.isalnum() or char in {"_", "-", "."} else "_" for char in str(chapter_id))
    while ".." in segment:
        segment = segment.replace("..", "_")
    return segment or "unassigned"


def _chapter_group(chapter_id: str) -> str:
    prefix = str(chapter_id or "").split(".", 1)[0]
    return f"chapter_{int(prefix):02d}" if prefix.isdigit() else f"chapter_{safe_segment(prefix or 'unassigned')}"
