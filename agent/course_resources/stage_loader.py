from __future__ import annotations

from copy import deepcopy
from typing import Any

from agent.tools.course_resource_tools import learning_path_resource_root, load_course_manifest, load_learning_path


def load_course_stages(
    course_id: str,
    *,
    path_id: str | None = None,
    resource_root: str | None = None,
) -> dict[str, Any]:
    course_manifest = load_course_manifest(course_id, resource_root=resource_root)
    selected_path_id = path_id or str(course_manifest.get("default_learning_path") or "standard")
    path_root = learning_path_resource_root(
        course_id,
        selected_path_id,
        resource_root=resource_root,
    )
    learning_path = load_learning_path(course_id, selected_path_id, resource_root=path_root)
    chapters = _ordered_chapters(learning_path)
    return {
        "course_id": course_manifest.get("course_id") or course_id,
        "course_title": course_manifest.get("course_title") or course_manifest.get("title") or "",
        "default_chapter_id": course_manifest.get("default_chapter_id") or _first_chapter_id(chapters),
        "path_id": learning_path.get("path_id") or selected_path_id,
        "path_title": learning_path.get("title") or selected_path_id,
        "profile_level": learning_path.get("profile_level") or selected_path_id,
        "generation_policy": deepcopy(learning_path.get("generation_policy") or {}),
        "chapters": [deepcopy(item) for item in chapters],
    }


def load_stage_prompt(
    course_id: str,
    chapter_id: str | None = None,
    *,
    content_type: str = "lecture",
    path_id: str | None = None,
    resource_root: str | None = None,
) -> dict[str, Any]:
    del content_type
    course = load_course_stages(course_id, path_id=path_id, resource_root=resource_root)
    selected_chapter_id = chapter_id or course["default_chapter_id"]
    chapter = _chapter_by_id(course["chapters"], selected_chapter_id)
    focus = _normalized_focus(chapter)
    return {
        "course_id": course["course_id"],
        "course_title": course["course_title"],
        "path_id": course["path_id"],
        "profile_level": course["profile_level"],
        "generation_policy": deepcopy(course["generation_policy"]),
        "chapter_id": chapter["chapter_id"],
        "chapter_title": chapter.get("chapter_title") or chapter["chapter_id"],
        "chapter_order": chapter.get("chapter_order") or 0,
        "next_chapter_id": chapter.get("next_chapter_id"),
        "required_material_types": list(focus["required_material_types"]),
        "chapter_focus": deepcopy(focus),
    }


def next_stage_id(
    course_id: str,
    current_chapter_id: str,
    *,
    path_id: str | None = None,
    resource_root: str | None = None,
) -> str | None:
    stage = load_stage_prompt(course_id, current_chapter_id, path_id=path_id, resource_root=resource_root)
    value = stage.get("next_chapter_id")
    return str(value) if value else None


def _ordered_chapters(learning_path: dict[str, Any]) -> list[dict[str, Any]]:
    chapters = learning_path.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        raise ValueError("learning path must contain a non-empty chapters list")
    normalized = [_normalized_chapter(item) for item in chapters if isinstance(item, dict)]
    normalized.sort(key=lambda item: int(item.get("chapter_order") or 0))
    return normalized


def _normalized_chapter(chapter: dict[str, Any]) -> dict[str, Any]:
    chapter_id = str(chapter.get("chapter_id") or "").strip()
    if not chapter_id:
        raise ValueError("learning path chapter missing chapter_id")
    result = deepcopy(chapter)
    result["chapter_id"] = chapter_id
    result.setdefault("chapter_title", chapter_id)
    result.setdefault("chapter_order", 0)
    result["focus"] = _normalized_focus(result)
    result["required_material_types"] = list(result["focus"]["required_material_types"])
    return result


def _normalized_focus(chapter: dict[str, Any]) -> dict[str, Any]:
    focus = chapter.get("focus") if isinstance(chapter.get("focus"), dict) else {}
    required = focus.get("required_material_types") or chapter.get("required_material_types") or ["lecture"]
    if not isinstance(required, list):
        required = ["lecture"]
    focus_items = focus.get("focus_items")
    if not isinstance(focus_items, list):
        focus_items = []
    return {
        "summary": str(focus.get("summary") or chapter.get("chapter_title") or chapter.get("chapter_id") or ""),
        "required_material_types": [str(item) for item in required if str(item).strip()],
        "focus_items": [item for item in focus_items if isinstance(item, dict)],
    }


def _chapter_by_id(chapters: list[dict[str, Any]], chapter_id: str) -> dict[str, Any]:
    for chapter in chapters:
        if str(chapter.get("chapter_id") or "") == chapter_id:
            return deepcopy(chapter)
    raise KeyError(f"unknown chapter_id: {chapter_id}")


def _first_chapter_id(chapters: list[dict[str, Any]]) -> str:
    if not chapters:
        raise ValueError("learning path has no chapters")
    return str(chapters[0]["chapter_id"])
