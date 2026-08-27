from __future__ import annotations

from typing import Any

from agent.course_resources.stage_loader import load_stage_prompt
from agent.node.node_logging import log_node_runtime
from agent.state import OverallState
from agent.tools.course_resource_tools import load_chapter_asset_bundle


@log_node_runtime("chapter_manifest_loader_node")
def chapter_manifest_loader_node(state: OverallState) -> OverallState:
    course_id = str(state.get("course_id") or "cnc_lathe")
    chapter_id = str(state.get("chapter_id") or "").strip()
    stage = load_stage_prompt(
        course_id,
        chapter_id or None,
        path_id=str(state.get("path_id") or "").strip() or None,
        resource_root=state.get("learning_path_resource_root"),
    )
    manifest = _manifest_from_stage(stage)
    resource_manifest: dict[str, Any] = {}
    asset_index: dict[str, Any] = {}
    missing_assets: list[dict[str, Any]] = []

    try:
        bundle = load_chapter_asset_bundle(
            course_id,
            stage["chapter_id"],
            resource_root=state.get("_course_resource_root"),
        )
    except (OSError, KeyError, ValueError) as exc:
        missing_assets.append(
            {
                "scope": "chapter_manifest",
                "course_id": course_id,
                "chapter_id": stage["chapter_id"],
                "reason": str(exc),
            }
        )
    else:
        resource_manifest = bundle.get("chapter_manifest") or {}
        manifest = resource_manifest or manifest
        asset_index = bundle.get("assets") if isinstance(bundle.get("assets"), dict) else {}

    focus = stage["chapter_focus"]
    required_material_types = [str(item) for item in stage["required_material_types"]]
    missing_assets.extend(
        _missing_required_assets(
            course_id,
            stage["chapter_id"],
            required_material_types,
            asset_index,
        )
    )
    effective_config = {
        "status": "partial" if missing_assets else "ready",
        "precedence": "learning_path",
        "course_id": course_id,
        "path_id": stage.get("path_id"),
        "path_version": str(state.get("path_version") or ""),
        "chapter_id": stage["chapter_id"],
        "chapter_title": stage.get("chapter_title") or stage["chapter_id"],
        "chapter_order": stage.get("chapter_order") or 0,
        "next_chapter_id": stage.get("next_chapter_id"),
        "focus": focus,
        "required_material_types": required_material_types,
        "resource_manifest": resource_manifest,
        "asset_index": asset_index,
        "missing_assets": missing_assets,
    }
    return {
        "chapter_manifest": manifest,
        "chapter_focus": focus,
        "required_material_types": required_material_types,
        "chapter_asset_index": asset_index,
        "missing_assets": missing_assets,
        "effective_chapter_config": effective_config,
    }


def _manifest_from_stage(stage: dict[str, Any]) -> dict[str, Any]:
    return {
        "course_id": stage["course_id"],
        "chapter_id": stage["chapter_id"],
        "title": stage.get("chapter_title") or stage["chapter_id"],
        "chapter_order": stage.get("chapter_order") or 0,
        "next_chapter_id": stage.get("next_chapter_id"),
        "focus": stage.get("chapter_focus") or {},
        "required_material_types": stage.get("required_material_types") or [],
    }


def _missing_required_assets(
    course_id: str,
    chapter_id: str,
    required_material_types: list[str],
    asset_index: dict[str, Any],
) -> list[dict[str, Any]]:
    aliases = {
        "lecture": "lecture",
        "practice": "practice",
        "quiz": "reference_quiz",
        "video": "videos",
        "videos": "videos",
        "operation_task": "operation_tasks",
        "operation_tasks": "operation_tasks",
    }
    missing = []
    for material_type in required_material_types:
        asset_key = aliases.get(material_type, material_type)
        if _has_available_asset(asset_index.get(asset_key)):
            continue
        missing.append(
            {
                "scope": "required_material",
                "course_id": course_id,
                "chapter_id": chapter_id,
                "material_type": material_type,
                "asset_key": asset_key,
                "reason": "required by learning path but no available chapter asset was indexed",
            }
        )
    return missing


def _has_available_asset(value: Any) -> bool:
    if isinstance(value, dict):
        if "exists" in value:
            return bool(value.get("exists"))
        return any(_has_available_asset(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_available_asset(item) for item in value)
    return bool(value)
