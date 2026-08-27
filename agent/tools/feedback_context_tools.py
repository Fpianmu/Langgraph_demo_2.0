from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agent.storage_layout import ensure_within, resolve_storage_root, safe_segment, user_root


def load_quiz_feedback_context(
    *,
    user_id: str,
    course_id: str,
    chapter_id: str,
    artifact_id: str,
    attempt_id: str,
    question_scope: str = "path_generated",
    storage_root: str | Path | None = None,
) -> dict[str, Any]:
    _safe_id(user_id, "user_id")
    _safe_id(course_id, "course_id")
    _safe_chapter_id(chapter_id)
    _safe_id(artifact_id, "artifact_id")
    _safe_id(attempt_id, "attempt_id")

    root = resolve_storage_root(storage_root)
    folder = _quiz_folder(
        root=root,
        user_id=user_id,
        chapter_id=chapter_id,
        artifact_id=artifact_id,
        question_scope=question_scope,
    )
    paths = {
        "manifest": _relative(root, folder / "manifest.json"),
        "questions": _relative(root, folder / "questions.json"),
        "attempt": _relative(root, folder / "attempts" / f"{safe_segment(attempt_id)}.json"),
    }
    manifest_path = ensure_within(root, root / paths["manifest"])
    questions_path = ensure_within(root, root / paths["questions"])
    attempt_path = ensure_within(root, root / paths["attempt"])
    missing = [
        label
        for label, path in (("manifest", manifest_path), ("questions", questions_path), ("attempt", attempt_path))
        if not path.exists()
    ]
    if missing:
        return _load_result("quiz_result", "not_found", paths, missing_files=missing)

    manifest = _read_json(manifest_path)
    question_set = _read_json(questions_path)
    attempt = _read_json(attempt_path)
    mismatches = []
    mismatches.extend(_field_mismatches("manifest", manifest, {"user_id": user_id, "course_id": course_id, "chapter_id": chapter_id, "artifact_id": artifact_id}))
    mismatches.extend(_field_mismatches("questions", question_set, {"user_id": user_id, "course_id": course_id, "chapter_id": chapter_id, "artifact_id": artifact_id}))
    mismatches.extend(_field_mismatches("attempt", attempt, {"user_id": user_id, "artifact_id": artifact_id, "attempt_id": attempt_id}))
    if mismatches:
        return _load_result("quiz_result", "invalid", paths, mismatched_fields=mismatches)

    items_by_id = {_question_id(item): item for item in _question_items(question_set) if _question_id(item)}
    answers = [item for item in attempt.get("answers") or [] if isinstance(item, dict)]
    wrong_items = []
    knowledge_results: dict[str, dict[str, Any]] = {}
    for answer in answers:
        question_id = str(answer.get("item_id") or answer.get("question_id") or "").strip()
        question = items_by_id.get(question_id, {})
        is_correct = bool(answer.get("is_correct"))
        knowledge_points = _knowledge_points(answer, question)
        core_exam_points = _core_exam_points(answer, question)
        for point in knowledge_points:
            result = knowledge_results.setdefault(point, {"correct_count": 0, "wrong_count": 0, "evidence": []})
            if is_correct:
                result["correct_count"] += 1
            else:
                result["wrong_count"] += 1
                result["evidence"].append(str(question.get("stem") or question.get("question_text") or question_id))
        if not is_correct:
            wrong_items.append(
                {
                    "question_id": question_id,
                    "stem": question.get("stem") or question.get("question_text") or "",
                    "knowledge_points": knowledge_points,
                    "core_exam_points": core_exam_points,
                    "capability_dimension": answer.get("capability_dimension") or question.get("capability_dimension"),
                    "score": answer.get("score"),
                    "possible": answer.get("possible"),
                    "grading_method": answer.get("grading_method"),
                    "grader_confidence": answer.get("grader_confidence"),
                    "key_point_coverage": answer.get("key_point_coverage") if isinstance(answer.get("key_point_coverage"), dict) else {},
                    "grading_result": answer.get("grading_result") if isinstance(answer.get("grading_result"), dict) else {},
                    "user_answer": answer.get("user_answer"),
                    "correct_answer": question.get("answer", question.get("correct_answer")),
                    "feedback": answer.get("feedback") or "",
                }
            )

    context = {
        "source_type": "quiz_result",
        "manifest": manifest,
        "question_set": question_set,
        "quiz_attempt": attempt,
        "answers": answers,
        "wrong_items": wrong_items,
        "knowledge_point_results": knowledge_results,
        "accuracy": _accuracy(attempt, answers),
    }
    return {
        "feedback_source_type": "quiz_result",
        "feedback_source_ids": {
            "user_id": user_id,
            "course_id": course_id,
            "chapter_id": chapter_id,
            "artifact_id": artifact_id,
            "attempt_id": attempt_id,
        },
        "feedback_context": context,
        "feedback_context_paths": paths,
        "feedback_context_load_result": {
            "status": "success",
            "missing_files": [],
            "mismatched_fields": [],
        },
    }


def load_qa_feedback_context(
    *,
    user_id: str,
    course_id: str,
    session_id: str,
    storage_root: str | Path | None = None,
    max_messages: int = 20,
) -> dict[str, Any]:
    _safe_id(user_id, "user_id")
    _safe_id(course_id, "course_id")
    _safe_id(session_id, "session_id")

    root = resolve_storage_root(storage_root)
    folder = user_root(root, user_id) / "conversations" / safe_segment(session_id)
    paths = {
        "manifest": _relative(root, folder / "manifest.json"),
        "messages": _relative(root, folder / "messages.jsonl"),
    }
    manifest_path = ensure_within(root, root / paths["manifest"])
    messages_path = ensure_within(root, root / paths["messages"])
    missing = [
        label for label, path in (("manifest", manifest_path), ("messages", messages_path)) if not path.exists()
    ]
    if missing:
        return _load_result("qa_dialogue", "not_found", paths, missing_files=missing)

    manifest = _read_json(manifest_path)
    messages = _read_jsonl(messages_path)
    if max_messages > 0:
        messages = messages[-max_messages:]
    mismatches = _field_mismatches("manifest", manifest, {"user_id": user_id, "course_id": course_id, "session_id": session_id})
    for index, message in enumerate(messages):
        if str(message.get("user_id") or "") != user_id:
            mismatches.append(f"message[{index}].user_id")
        if str(message.get("session_id") or "") != session_id:
            mismatches.append(f"message[{index}].session_id")
    if mismatches:
        return _load_result("qa_dialogue", "invalid", paths, mismatched_fields=mismatches)

    context = {
        "source_type": "qa_dialogue",
        "qa_session": manifest,
        "qa_messages": messages,
        "context_text": _messages_text(messages),
    }
    return {
        "feedback_source_type": "qa_dialogue",
        "feedback_source_ids": {
            "user_id": user_id,
            "course_id": course_id,
            "session_id": session_id,
        },
        "feedback_context": context,
        "qa_messages": messages,
        "feedback_context_paths": paths,
        "feedback_context_load_result": {
            "status": "success",
            "missing_files": [],
            "mismatched_fields": [],
        },
    }


def _load_result(
    source_type: str,
    status: str,
    paths: dict[str, str],
    *,
    missing_files: list[str] | None = None,
    mismatched_fields: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "feedback_source_type": source_type,
        "feedback_context_paths": paths,
        "feedback_context_load_result": {
            "status": status,
            "missing_files": missing_files or [],
            "mismatched_fields": mismatched_fields or [],
        },
    }


def _quiz_folder(root: Path, user_id: str, chapter_id: str, artifact_id: str, question_scope: str) -> Path:
    questions = user_root(root, user_id) / "questions"
    if str(question_scope or "") == "custom_generated":
        return questions / "custom_generated" / safe_segment(artifact_id)
    return questions / "path_generated" / _chapter_group(chapter_id) / chapter_id / safe_segment(artifact_id)


def _safe_id(value: str, field: str) -> None:
    raw = str(value or "").strip()
    if not raw or safe_segment(raw) != raw:
        raise ValueError(f"unsafe {field}: {value}")


def _safe_chapter_id(value: str) -> None:
    raw = str(value or "").strip()
    if not raw or ".." in raw or raw in {".", ".."} or not re.match(r"^[0-9A-Za-z_.-]+$", raw):
        raise ValueError(f"unsafe chapter_id: {value}")


def _chapter_group(chapter_id: str) -> str:
    prefix = str(chapter_id or "").split(".", 1)[0]
    try:
        number = int(prefix)
    except ValueError:
        return "chapter_misc"
    return f"chapter_{number:02d}"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    messages = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            messages.append(value)
    return messages


def _field_mismatches(prefix: str, data: dict[str, Any], expected: dict[str, str]) -> list[str]:
    return [f"{prefix}.{field}" for field, value in expected.items() if str(data.get(field) or "") != value]


def _question_items(question_set: dict[str, Any]) -> list[dict[str, Any]]:
    value = question_set.get("items") or question_set.get("questions")
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _question_id(question: dict[str, Any]) -> str:
    return str(question.get("id") or question.get("item_id") or question.get("question_id") or "").strip()


def _knowledge_points(answer: dict[str, Any], question: dict[str, Any]) -> list[str]:
    return _named_points(answer.get("knowledge_points") or question.get("knowledge_points") or question.get("core_points"))


def _core_exam_points(answer: dict[str, Any], question: dict[str, Any]) -> list[str]:
    return _named_points(answer.get("core_exam_points") or question.get("core_exam_points"))


def _named_points(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if isinstance(item, dict):
            text = str(item.get("name") or item.get("id") or "").strip()
        else:
            text = str(item).strip()
        if text:
            result.append(text)
    return result


def _accuracy(attempt: dict[str, Any], answers: list[dict[str, Any]]) -> float:
    if "accuracy" in attempt:
        try:
            return max(0.0, min(float(attempt.get("accuracy")), 1.0))
        except (TypeError, ValueError):
            return 0.0
    if not answers:
        return 0.0
    return round(sum(1 for item in answers if item.get("is_correct")) / len(answers), 4)


def _messages_text(messages: list[dict[str, Any]]) -> str:
    lines = []
    for message in messages:
        role = str(message.get("role") or "message")
        content = str(message.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _relative(root: Path, path: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")
