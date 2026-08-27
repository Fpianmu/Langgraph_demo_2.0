from __future__ import annotations

from typing import Any

from langgraph.types import Command

from agent.node.node_logging import log_node_runtime
from agent.state import OverallState
from agent.tools.course_resource_tools import learning_path_resource_root, load_course_manifest, load_learning_path
from agent.tools.profile_tools import load_profile_context


@log_node_runtime("learning_path_resolver_node")
def learning_path_resolver_node(state: OverallState) -> Command[str]:
    user_id = str(state.get("user_id") or "default_user")
    course_id = str(state.get("course_id") or "cnc_lathe")
    storage_root = state.get("_storage_root")
    resource_root = state.get("_course_resource_root")
    profile_context = load_profile_context(user_id=user_id, storage_root=storage_root)
    assignment = _assignment_for_course(profile_context.get("path_assignments"), course_id)
    course_manifest = load_course_manifest(course_id, resource_root=resource_root)
    default_path_id = str(course_manifest.get("default_learning_path") or "standard")
    requested_path_id = str((assignment or {}).get("path_id") or default_path_id)
    status = "assigned" if assignment else "course_default"

    try:
        path_root = learning_path_resource_root(
            course_id,
            requested_path_id,
            resource_root=resource_root,
        )
        learning_path = load_learning_path(course_id, requested_path_id, resource_root=path_root)
        selected_path_id = requested_path_id
    except (FileNotFoundError, KeyError):
        if requested_path_id == default_path_id:
            raise
        path_root = learning_path_resource_root(
            course_id,
            default_path_id,
            resource_root=resource_root,
        )
        learning_path = load_learning_path(course_id, default_path_id, resource_root=path_root)
        selected_path_id = default_path_id
        status = "fallback_invalid_assignment"

    assigned_level = (assignment or {}).get("learner_level") if status == "assigned" else None
    learner_level = str(assigned_level or learning_path.get("profile_level") or selected_path_id)
    path_version = str(
        ((assignment or {}).get("path_version") if status == "assigned" else "")
        or learning_path.get("version")
        or course_manifest.get("version")
        or ""
    )
    assignment_updated_at = str((assignment or {}).get("updated_at") or "") if status == "assigned" else ""
    resolution = {
        "status": status,
        "user_id": user_id,
        "course_id": course_id,
        "requested_path_id": requested_path_id,
        "selected_path_id": selected_path_id,
        "path_version": path_version,
        "assignment": assignment,
    }
    return Command(
        update={
            "progress_profile_context": profile_context,
            "path_assignment": assignment,
            "path_id": selected_path_id,
            "path_version": path_version,
            "assignment_updated_at": assignment_updated_at,
            "learner_level": learner_level,
            "learning_path": learning_path,
            "learning_path_resource_root": str(path_root) if path_root is not None else None,
            "generation_policy": dict(learning_path.get("generation_policy") or {}),
            "learning_path_resolution": resolution,
        },
        goto="progress_advance_node",
    )


def _assignment_for_course(value: Any, course_id: str) -> dict[str, Any] | None:
    if not isinstance(value, list):
        return None
    for item in value:
        if isinstance(item, dict) and str(item.get("course_id") or "") == course_id:
            return dict(item)
    return None
