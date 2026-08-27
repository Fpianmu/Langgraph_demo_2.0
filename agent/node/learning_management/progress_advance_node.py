from __future__ import annotations

import logging
from typing import Any

from langgraph.types import Command

from agent.course_resources.stage_loader import load_stage_prompt, next_stage_id
from agent.node.node_logging import log_node_runtime
from agent.state import OverallState
from agent.tools.profile_tools import apply_profile_update_suggestions, load_profile_context


LOGGER = logging.getLogger("agent.progress_advance")


@log_node_runtime("progress_advance_node")
def progress_advance_node(state: OverallState) -> Command[str]:
    user_id = str(state.get("user_id") or "default_user")
    request_id = str(state.get("request_id") or "")
    course_id = str(state.get("course_id") or "cnc_lathe")
    profile_context = state.get("progress_profile_context")
    if not isinstance(profile_context, dict):
        profile_context = load_profile_context(user_id=user_id, storage_root=state.get("_storage_root"))
    path_assignment = state.get("path_assignment")
    if not isinstance(path_assignment, dict):
        path_assignment = _assigned_path_assignment(profile_context, course_id)
    path_id = str(state.get("path_id") or (path_assignment or {}).get("path_id") or "").strip() or None
    path_version = str(state.get("path_version") or (path_assignment or {}).get("path_version") or "")
    assignment_updated_at = str(
        state.get("assignment_updated_at") or (path_assignment or {}).get("updated_at") or ""
    )
    resource_root = state.get("learning_path_resource_root")
    previous_chapter_id = _current_chapter_id(state, profile_context, course_id, path_id)
    target_chapter_id = _target_chapter_id(
        course_id,
        previous_chapter_id,
        path_id=path_id,
        resource_root=resource_root,
    )
    stage = load_stage_prompt(
        course_id,
        target_chapter_id,
        path_id=path_id,
        resource_root=resource_root,
    )
    update_result = apply_profile_update_suggestions(
        user_id=user_id,
        request_id=request_id,
        suggestions={
            "progress_patches": [
                {
                    "course_id": course_id,
                    "path_id": stage.get("path_id") or "",
                    "path_version": path_version,
                    "chapter_id": stage["chapter_id"],
                    "chapter_order": stage.get("chapter_order") or 0,
                    "assignment_updated_at": assignment_updated_at,
                    "status": "in_progress",
                    "completion_rate": 0.0,
                }
            ],
            "markdown_patch": {
                "section": "学习进度",
                "content": f"已进入：{stage['chapter_title']}。",
            },
        },
        storage_root=state.get("_storage_root"),
    )
    LOGGER.info(
        "progress_advance_node advanced stage user_id=%s course_id=%s from_chapter_id=%s to_chapter_id=%s",
        user_id,
        course_id,
        previous_chapter_id or "",
        stage["chapter_id"],
    )
    update = {
        "pipeline_type": "progress",
        "progress_profile_context": profile_context,
        "previous_chapter_id": previous_chapter_id,
        "course_id": course_id,
        "path_id": stage.get("path_id"),
        "path_version": path_version,
        "assignment_updated_at": assignment_updated_at,
        "learner_level": state.get("learner_level") or stage.get("profile_level"),
        "generation_policy": stage.get("generation_policy") or {},
        "chapter_id": stage["chapter_id"],
        "learning_stage": {
            "course_id": stage["course_id"],
            "course_title": stage["course_title"],
            "path_id": stage.get("path_id"),
            "path_version": path_version,
            "assignment_updated_at": assignment_updated_at,
            "learner_level": state.get("learner_level") or stage.get("profile_level"),
            "generation_policy": stage.get("generation_policy") or {},
            "chapter_id": stage["chapter_id"],
            "chapter_title": stage["chapter_title"],
            "chapter_order": stage["chapter_order"],
            "required_material_types": stage.get("required_material_types") or [],
            "chapter_focus": stage.get("chapter_focus") or {},
        },
        "next_chapter_id": stage.get("next_chapter_id"),
        "progress_advance_result": {
            "status": "success",
            "from_chapter_id": previous_chapter_id,
            "to_chapter_id": stage["chapter_id"],
            "profile_update_result": update_result,
        },
    }
    return Command(update=update, goto="chapter_manifest_loader_node")


def _current_chapter_id(
    state: OverallState,
    profile_context: dict[str, Any],
    course_id: str,
    path_id: str | None,
) -> str | None:
    explicit = str(state.get("chapter_id") or "").strip()
    if explicit:
        return explicit
    progress = profile_context.get("learning_progress")
    if not isinstance(progress, list):
        return None
    course_progress = [
        item
        for item in progress
        if isinstance(item, dict) and str(item.get("course_id") or "") == course_id
    ]
    if path_id:
        path_progress = [item for item in course_progress if str(item.get("path_id") or "") == path_id]
        legacy_progress = [item for item in course_progress if not str(item.get("path_id") or "").strip()]
        course_progress = path_progress or legacy_progress
    for status in ("in_progress", "needs_review", "learning"):
        chapter_id = _first_chapter_with_status(course_progress, status)
        if chapter_id:
            return chapter_id
    for item in course_progress:
        chapter_id = str(item.get("chapter_id") or "").strip()
        if chapter_id:
            return chapter_id
    return None


def _first_chapter_with_status(progress: list[dict[str, Any]], status: str) -> str | None:
    for item in progress:
        if str(item.get("status") or "").strip() != status:
            continue
        chapter_id = str(item.get("chapter_id") or "").strip()
        if chapter_id:
            return chapter_id
    return None


def _target_chapter_id(
    course_id: str,
    previous_chapter_id: str | None,
    *,
    path_id: str | None,
    resource_root: str | None,
) -> str | None:
    if not previous_chapter_id:
        return None
    return next_stage_id(
        course_id,
        previous_chapter_id,
        path_id=path_id,
        resource_root=resource_root,
    ) or previous_chapter_id


def _assigned_path_assignment(profile_context: dict[str, Any], course_id: str) -> dict[str, Any] | None:
    assignments = profile_context.get("path_assignments")
    if not isinstance(assignments, list):
        return None
    for item in assignments:
        if not isinstance(item, dict) or str(item.get("course_id") or "") != course_id:
            continue
        return dict(item)
    return None
