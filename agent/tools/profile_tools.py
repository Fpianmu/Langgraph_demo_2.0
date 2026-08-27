from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.tools.profile.manager import ProfileManager


def load_profile_context(
    *,
    user_id: str,
    display_name: str | None = None,
    background_type: str | None = None,
    storage_root: str | Path | None = None,
) -> dict[str, Any]:
    return ProfileManager(storage_root).load_profile_context(
        user_id,
        display_name=display_name,
        background_type=background_type,
    )


def apply_profile_update_suggestions(
    *,
    user_id: str,
    request_id: str,
    suggestions: dict[str, Any],
    storage_root: str | Path | None = None,
) -> dict[str, Any]:
    return ProfileManager(storage_root).apply_update_suggestions(user_id, request_id, suggestions)


def assign_user_learning_path(
    *,
    user_id: str,
    course_id: str,
    learner_level: str,
    path_id: str,
    path_version: str = "",
    classification_source: str = "registration",
    classification_score: float | None = None,
    classification_reason: str = "",
    manual_override: bool = False,
    storage_root: str | Path | None = None,
) -> dict[str, Any]:
    return ProfileManager(storage_root).assign_learning_path(
        user_id,
        {
            "course_id": course_id,
            "learner_level": learner_level,
            "path_id": path_id,
            "path_version": path_version,
            "classification_source": classification_source,
            "classification_score": classification_score,
            "classification_reason": classification_reason,
            "manual_override": manual_override,
        },
    )


def record_resource_difficulty(
    *,
    user_id: str,
    record: dict[str, Any],
    storage_root: str | Path | None = None,
) -> dict[str, Any]:
    return ProfileManager(storage_root).record_resource_difficulty(user_id, record)


def load_resource_difficulty_trace(
    *,
    user_id: str,
    storage_root: str | Path | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    return ProfileManager(storage_root).load_resource_difficulty_trace(user_id, limit=limit)


def register_user_profile(
    *,
    user_id: str,
    course_id: str,
    learner_level: str,
    display_name: str | None = None,
    background_type: str | None = None,
    path_id: str | None = None,
    classification_score: float | None = None,
    classification_reason: str = "",
    classification_source: str = "registration_assessment",
    storage_root: str | Path | None = None,
    resource_root: str | Path | None = None,
) -> dict[str, Any]:
    from agent.tools.course_resource_tools import load_course_manifest, load_learning_path

    manifest = load_course_manifest(course_id, resource_root=resource_root)
    supported_levels = {
        str(item)
        for item in manifest.get("learning_levels", [])
        if str(item).strip()
    }
    if learner_level not in supported_levels:
        raise ValueError(f"unsupported learner_level for {course_id}: {learner_level}")

    selected_path_id = str(path_id or learner_level)
    learning_path = load_learning_path(course_id, selected_path_id, resource_root=resource_root)
    manager = ProfileManager(storage_root)
    manager.load_profile_context(
        user_id,
        display_name=display_name,
        background_type=background_type,
    )
    assignment = manager.assign_learning_path(
        user_id,
        {
            "course_id": course_id,
            "learner_level": learner_level,
            "path_id": selected_path_id,
            "path_version": str(manifest.get("version") or learning_path.get("version") or ""),
            "classification_source": classification_source,
            "classification_score": classification_score,
            "classification_reason": classification_reason,
            "manual_override": False,
        },
    )
    return {
        "status": "registered",
        "user_id": user_id,
        "course_id": course_id,
        "path_assignment": assignment,
        "learning_path": learning_path,
        "profile_context": manager.load_profile_context(user_id),
    }
