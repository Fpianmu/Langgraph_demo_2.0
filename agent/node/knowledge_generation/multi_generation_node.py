from __future__ import annotations

import logging
from typing import Any, Callable

from agent.node.knowledge_generation.generators import (
    lecture_generator,
    practice_guide_generator,
    qa_answer_generator,
    question_generator,
)
from agent.node.node_logging import log_node_runtime
from agent.state import OverallState


LOGGER = logging.getLogger("agent.multi_generation")


GENERATOR_BY_KIND: dict[str, Callable[[OverallState], OverallState]] = {
    "lecture": lecture_generator,
    "practice": practice_guide_generator,
    "quiz": question_generator,
    "qa": qa_answer_generator,
}


@log_node_runtime("multi_generation_node")
def multi_generation_node(state: OverallState) -> OverallState:
    prompts = _generation_prompts_from_state(state)
    updates: OverallState = {}
    materials: dict[str, Any] = {}

    for kind, prompt in prompts.items():
        if not prompt:
            continue
        generator = GENERATOR_BY_KIND[kind]
        generator_state: OverallState = {
            **state,
            "task": prompt,
            "content_type": _content_type_for_kind(kind),
        }
        LOGGER.info("multi_generation_node running generator kind=%s prompt_length=%d", kind, len(prompt))
        result = generator(generator_state)
        updates.update(result)
        generated = _generated_content_for_kind(kind, result)
        if generated:
            materials[kind] = generated

    updates["generated_materials"] = materials
    updates["final_materials"] = materials
    if materials and "generated_content" not in updates:
        first_material = next(iter(materials.values()))
        updates["generated_content"] = first_material
        updates["final_output"] = first_material
    return updates


def _generation_prompts_from_state(state: OverallState) -> dict[str, str]:
    raw_prompts = state.get("stage_generation_prompts")
    prompts = raw_prompts if isinstance(raw_prompts, dict) else {}
    return {
        "lecture": _clean_prompt(prompts.get("lecture") or state.get("lecture_generation_prompt")),
        "practice": _clean_prompt(prompts.get("practice") or state.get("practice_generation_prompt")),
        "quiz": _clean_prompt(prompts.get("quiz") or state.get("quiz_generation_prompt")),
        "qa": _clean_prompt(prompts.get("qa") or state.get("qa_generation_prompt")),
    }


def _generated_content_for_kind(kind: str, result: OverallState) -> dict[str, Any]:
    field_name = {
        "lecture": "generated_lecture_content",
        "practice": "generated_practice_guide_content",
        "quiz": "generated_question_content",
        "qa": "generated_qa_content",
    }[kind]
    value = result.get(field_name)
    return value if isinstance(value, dict) else {}


def _content_type_for_kind(kind: str) -> str:
    return "practice" if kind == "practice" else kind


def _clean_prompt(value: Any) -> str:
    return str(value or "").strip()
