from __future__ import annotations

import copy
import json
import re
from typing import Any

from agent.state import OverallState


def get_review_materials(state: OverallState) -> dict[str, dict[str, Any]]:
    materials = state.get("verification_materials")
    if isinstance(materials, dict) and materials:
        return {str(key): value for key, value in materials.items() if isinstance(value, dict)}
    final_materials = state.get("final_materials")
    if isinstance(final_materials, dict) and final_materials:
        return {str(key): value for key, value in final_materials.items() if isinstance(value, dict)}
    final_output = state.get("final_output")
    if isinstance(final_output, dict) and final_output:
        return {"single": final_output}
    personalized = state.get("personalized_output")
    if isinstance(personalized, dict) and personalized:
        return {"single": personalized}
    return {}


def collect_evidence(state: OverallState) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for key in ("rag_package", "patch_rag_package", "quiz_rag_package"):
        package = state.get(key)
        if isinstance(package, dict):
            items.extend(_normalize_rag_evidence(package.get("evidence"), source_type=key))
    items.extend(_manual_text_evidence(state.get("manual_lecture_content"), "manual_lecture"))
    items.extend(_manual_text_evidence(state.get("manual_practice_content"), "manual_practice"))
    reference_quiz = state.get("reference_quiz")
    if isinstance(reference_quiz, dict):
        items.extend(_reference_quiz_evidence(reference_quiz))
    extra = state.get("verification_extra_evidence")
    if isinstance(extra, list):
        items.extend(item for item in extra if isinstance(item, dict))
    return dedupe_evidence(items)


def dedupe_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        source_file = str(item.get("source_file") or item.get("source_doc") or item.get("source_type") or "")
        chunk_id = str(item.get("chunk_id") or "")
        text = str(item.get("text") or "").strip()
        key = (source_file, chunk_id, text[:120])
        if not text or key in seen:
            continue
        seen.add(key)
        normalized = dict(item)
        normalized["source_file"] = source_file
        normalized["chunk_id"] = chunk_id or f"chunk_{len(result) + 1:04d}"
        normalized["text"] = text
        result.append(normalized)
    return result


def apply_allowed_patches(material: dict[str, Any], patches: list[dict[str, Any]], material_type: str) -> dict[str, Any]:
    updated = copy.deepcopy(material)
    for patch in patches:
        if not isinstance(patch, dict) or patch.get("op") != "replace":
            continue
        path = str(patch.get("path") or "")
        if not _path_allowed(path, material_type, updated):
            continue
        _replace_json_pointer(updated, path, patch.get("value"))
    return updated


def write_review_materials(state: OverallState, materials: dict[str, dict[str, Any]]) -> OverallState:
    update: OverallState = {"verification_materials": materials}
    if state.get("final_materials") or len(materials) > 1 or any(key != "single" for key in materials):
        update["final_materials"] = materials
        update["personalized_output"] = {
            "meta": {"status": "success", "verification_rewrite": True},
            "materials": materials,
        }
        update["final_output"] = update["personalized_output"]
        for kind, material in materials.items():
            update.update(_type_specific_update(kind, material))
    else:
        material = materials.get("single") or {}
        update["final_output"] = material
        update["personalized_output"] = material
        update.update(_type_specific_update(_content_type(material, state), material))
    return update


def json_loads_object(text: str) -> dict[str, Any]:
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if not match:
            return {}
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
    return value if isinstance(value, dict) else {}


def human_message(content: str) -> Any:
    try:
        from langchain.messages import HumanMessage
    except ModuleNotFoundError:
        from langchain_core.messages import HumanMessage
    return HumanMessage(content)


def evidence_prompt_text(evidence: list[dict[str, Any]], *, limit: int = 12) -> str:
    lines = []
    for index, item in enumerate(evidence[:limit], start=1):
        lines.append(
            f"[{index}] source_file={item.get('source_file')}; chunk_id={item.get('chunk_id')}\n"
            f"{str(item.get('text') or '')[:1200]}"
        )
    return "\n\n".join(lines) if lines else "No evidence."


def _normalize_rag_evidence(value: Any, *, source_type: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "source_type": source_type,
                "source_file": str(item.get("source_file") or item.get("source_doc") or source_type),
                "chunk_id": str(item.get("chunk_id") or ""),
                "text": str(item.get("text") or ""),
                "trust_level": "rag",
            }
        )
    return result


def _manual_text_evidence(value: Any, source_type: str) -> list[dict[str, Any]]:
    text = str(value or "").strip()
    if not text:
        return []
    chunks = []
    for index, chunk in enumerate(_split_text(text), start=1):
        chunks.append(
            {
                "source_type": source_type,
                "source_file": source_type,
                "chunk_id": f"{source_type}_{index:04d}",
                "text": chunk,
                "trust_level": "course_resource",
            }
        )
    return chunks


def _reference_quiz_evidence(value: dict[str, Any]) -> list[dict[str, Any]]:
    questions = value.get("questions")
    if not isinstance(questions, list):
        return []
    result = []
    for index, question in enumerate(questions, start=1):
        if isinstance(question, dict):
            result.append(
                {
                    "source_type": "reference_quiz",
                    "source_file": "reference_quiz",
                    "chunk_id": f"reference_quiz_{index:04d}",
                    "text": json.dumps(question, ensure_ascii=False),
                    "trust_level": "course_resource",
                }
            )
    return result


def _split_text(text: str, chunk_size: int = 1000, overlap: int = 120) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    chunks = []
    start = 0
    while start < len(cleaned):
        end = min(start + chunk_size, len(cleaned))
        chunks.append(cleaned[start:end].strip())
        if end == len(cleaned):
            break
        start = max(start + 1, end - overlap)
    return chunks


def _path_allowed(path: str, material_type: str, material: dict[str, Any]) -> bool:
    content_type = material_type if material_type != "single" else _content_type(material, {})
    if path == "/summary":
        return True
    if content_type == "lecture":
        return bool(re.fullmatch(r"/payload/sections/\d+/content", path))
    if content_type in {"practice", "practice_guide"}:
        return bool(
            re.fullmatch(r"/payload/(objectives|steps|checklist|safety_points)/\d+", path)
        )
    if content_type in {"quiz", "question", "questions"}:
        return bool(re.fullmatch(r"/payload/questions/\d+", path))
    if content_type in {"qa", "qa_answer"}:
        return path == "/payload/answer"
    return False


def _replace_json_pointer(value: dict[str, Any], path: str, replacement: Any) -> None:
    parts = [part.replace("~1", "/").replace("~0", "~") for part in path.strip("/").split("/") if part]
    current: Any = value
    for part in parts[:-1]:
        current = current[int(part)] if isinstance(current, list) else current[part]
    last = parts[-1]
    if isinstance(current, list):
        current[int(last)] = replacement
    else:
        current[last] = replacement


def _type_specific_update(kind: str, material: dict[str, Any]) -> OverallState:
    content_type = "practice" if kind == "practice_guide" else kind
    if content_type == "single":
        content_type = _content_type(material, {})
    mapping = {
        "lecture": "personalized_lecture_output",
        "practice": "personalized_practice_guide_output",
        "quiz": "personalized_question_output",
        "qa": "personalized_qa_output",
    }
    field = mapping.get(content_type)
    return {field: material} if field else {}


def _content_type(material: dict[str, Any], state: dict[str, Any]) -> str:
    meta = material.get("meta")
    if isinstance(meta, dict) and meta.get("content_type"):
        return str(meta["content_type"])
    return str(state.get("content_type") or "")
