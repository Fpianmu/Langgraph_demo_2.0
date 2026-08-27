from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.course_resources.repository import CourseResourceRepository


def load_course_manifest(
    course_id: str,
    *,
    resource_root: str | Path | None = None,
) -> dict[str, Any]:
    return CourseResourceRepository(resource_root).load_course_manifest(course_id)


def load_learning_path(
    course_id: str,
    path_id: str,
    *,
    resource_root: str | Path | None = None,
) -> dict[str, Any]:
    return CourseResourceRepository(resource_root).load_learning_path(course_id, path_id)


def learning_path_resource_root(
    course_id: str,
    path_id: str,
    *,
    resource_root: str | Path | None = None,
) -> str | Path | None:
    """Use an injected resource root only when it contains the complete path file."""
    if resource_root is None:
        return None
    try:
        CourseResourceRepository(resource_root).load_learning_path(course_id, path_id)
    except (FileNotFoundError, KeyError):
        return None
    return resource_root


def load_chapter_asset_bundle(
    course_id: str,
    chapter_id: str,
    *,
    resource_root: str | Path | None = None,
) -> dict[str, Any]:
    return CourseResourceRepository(resource_root).load_chapter_asset_bundle(course_id, chapter_id)


def load_manual_lecture(
    course_id: str,
    chapter_id: str,
    *,
    resource_root: str | Path | None = None,
) -> dict[str, Any]:
    return CourseResourceRepository(resource_root).load_manual_lecture(course_id, chapter_id)


def load_reference_quiz(
    course_id: str,
    chapter_id: str,
    *,
    resource_root: str | Path | None = None,
) -> dict[str, Any]:
    return CourseResourceRepository(resource_root).load_reference_quiz(course_id, chapter_id)


def load_operation_task_bundle(
    course_id: str,
    chapter_id: str,
    task_id: str,
    *,
    resource_root: str | Path | None = None,
) -> dict[str, Any]:
    return CourseResourceRepository(resource_root).load_operation_task_bundle(course_id, chapter_id, task_id)


def load_workpiece_standard_spec(
    course_id: str,
    workpiece_id: str,
    *,
    resource_root: str | Path | None = None,
) -> dict[str, Any]:
    return CourseResourceRepository(resource_root).load_workpiece_standard_spec(course_id, workpiece_id)
