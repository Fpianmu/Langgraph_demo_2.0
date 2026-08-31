from __future__ import annotations

from agent.node.node_logging import log_node_runtime
from agent.node.verification_utils import get_review_materials
from agent.node.personalized_generation.personalization_node import (
    _normalized_content_type,
    _save_markdown_material,
    _save_qa_material,
    _save_question_material,
    _saved_material_update,
)
from agent.state import OverallState
from agent.tools.profile.manager import ProfileManager


@log_node_runtime("verified_persistence_node")
def verified_persistence_node(state: OverallState) -> OverallState:
    materials = get_review_materials(state)
    update: OverallState = {}
    if len(materials) == 1 and "single" in materials:
        update["verified_output"] = materials["single"]
    else:
        update["verified_materials"] = materials
    if not (state.get("user_id") or state.get("_storage_root")):
        return update

    saved_outputs: dict[str, object] = {}
    for kind, material in materials.items():
        content_type = _normalized_content_type(kind, material, state)
        if content_type in {"lecture", "practice"}:
            saved = _save_markdown_material(state, material, content_type=content_type)
            saved_outputs[content_type] = saved
            update.update(_saved_material_update(content_type, saved))
        elif content_type in {"quiz", "question", "questions"}:
            saved = _save_question_material(state, material)
            saved_outputs["quiz"] = saved
            update.update(_saved_material_update("quiz", saved))
        elif content_type in {"qa", "qa_answer"}:
            saved = _save_qa_material(state, material)
            saved_outputs["qa"] = saved
            update.update(_saved_material_update("qa", saved))
    if saved_outputs:
        update["saved_outputs"] = saved_outputs
        _record_resource_difficulties(state, saved_outputs)
    return update


def _record_resource_difficulties(state: OverallState, saved_outputs: dict[str, object]) -> None:
    user_id = str(state.get("user_id") or "").strip()
    if not user_id:
        return
    manager = ProfileManager(state.get("_storage_root"))
    profile_score = manager.load_profile_context(user_id).get("capability_profile_score", {})
    for content_type, value in saved_outputs.items():
        if content_type not in {"lecture", "practice", "quiz"} or not isinstance(value, dict):
            continue
        manager.record_generated_resource_difficulty(
            user_id,
            {
                **value,
                "artifact_type": content_type,
                "chapter_id": str(state.get("chapter_id") or ""),
                "course_id": str(state.get("course_id") or ""),
                "title": str(value.get("title") or ""),
            },
            profile_score=profile_score,
            source_node="verified_persistence_node",
        )
