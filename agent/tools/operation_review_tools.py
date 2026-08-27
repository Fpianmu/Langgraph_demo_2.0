from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.storage_layout import resolve_storage_root, safe_segment, user_root


def operation_review_paths(
    *,
    user_id: str,
    chapter_id: str,
    task_id: str,
    submission_id: str,
    storage_root: str | Path | None = None,
) -> dict[str, str]:
    root = resolve_storage_root(storage_root)
    task_folder = (
        user_root(root, user_id)
        / "questions"
        / "path_generated"
        / _chapter_group(chapter_id)
        / _chapter_segment(chapter_id)
        / f"operation_{safe_segment(task_id)}"
    )
    submission_folder = task_folder / "submissions" / safe_segment(submission_id)
    return {
        "manifest": _relative(root, task_folder / "manifest.json"),
        "submission_folder": _relative(root, submission_folder),
        "submission": _relative(root, submission_folder / "submission.json"),
        "uploaded_images": _relative(root, submission_folder / "uploaded_images"),
        "measurement_params": _relative(root, submission_folder / "measurement_params.json"),
        "vl_analysis_result": _relative(root, submission_folder / "vl_analysis_result.json"),
        "measurement_comparison_result": _relative(root, submission_folder / "measurement_comparison_result.json"),
        "operation_review_result": _relative(root, submission_folder / "operation_review_result.json"),
        "llm_review_report": _relative(root, submission_folder / "llm_review_report.md"),
    }


def save_operation_submission(
    *,
    user_id: str,
    course_id: str,
    chapter_id: str,
    task_id: str,
    workpiece_id: str,
    submission_id: str,
    uploaded_images: list[dict[str, Any]],
    measurement_params: dict[str, Any],
    static_task_ref: str,
    storage_root: str | Path | None = None,
) -> dict[str, str]:
    root = resolve_storage_root(storage_root)
    paths = operation_review_paths(
        user_id=user_id,
        chapter_id=chapter_id,
        task_id=task_id,
        submission_id=submission_id,
        storage_root=storage_root,
    )
    task_manifest_path = root / paths["manifest"]
    submission_folder = root / paths["submission_folder"]
    images_folder = root / paths["uploaded_images"]
    submission_folder.mkdir(parents=True, exist_ok=True)
    images_folder.mkdir(parents=True, exist_ok=True)

    task_manifest = {
        "source": "path_generated",
        "question_source": "course_resources",
        "course_id": course_id,
        "chapter_id": chapter_id,
        "task_id": task_id,
        "workpiece_id": workpiece_id,
        "static_task_ref": static_task_ref,
    }
    _write_json(task_manifest_path, task_manifest)
    _write_json(root / paths["measurement_params"], measurement_params)
    _write_json(
        root / paths["submission"],
        {
            "submission_id": submission_id,
            "user_id": user_id,
            "course_id": course_id,
            "chapter_id": chapter_id,
            "task_id": task_id,
            "workpiece_id": workpiece_id,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "uploaded_images": uploaded_images,
            "measurement_params_ref": "measurement_params.json",
        },
    )
    return paths


def write_operation_review_json(
    *,
    relative_path: str,
    payload: dict[str, Any],
    storage_root: str | Path | None = None,
) -> None:
    root = resolve_storage_root(storage_root)
    _write_json(root / relative_path, payload)


def write_operation_review_markdown(
    *,
    relative_path: str,
    content: str,
    storage_root: str | Path | None = None,
) -> None:
    root = resolve_storage_root(storage_root)
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _relative(root: Path, path: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def _chapter_segment(chapter_id: str) -> str:
    segment = "".join(char if char.isalnum() or char in {"_", "-", "."} else "_" for char in str(chapter_id))
    while ".." in segment:
        segment = segment.replace("..", "_")
    if segment in {"", ".", ".."}:
        return "_"
    return segment


def _chapter_group(chapter_id: str) -> str:
    prefix = str(chapter_id or "").split(".", 1)[0]
    if prefix.isdigit():
        return f"chapter_{int(prefix):02d}"
    return f"chapter_{safe_segment(prefix or 'unassigned')}"
