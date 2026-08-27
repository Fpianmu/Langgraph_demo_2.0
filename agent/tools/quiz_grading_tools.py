from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from agent.tools.learning_archive.manager import LearningArchiveManager


GRADING_VERSION = "demo2-lightweight-quiz-grader-v1"


class QuizQuestionNotFound(Exception):
    def __init__(self, question_id: str) -> None:
        super().__init__(f"question not found: {question_id}")
        self.question_id = question_id


class QuizSubmissionInvalid(Exception):
    pass


def submit_quiz_answers(
    *,
    user_id: str,
    artifact_id: str,
    answers: list[dict[str, Any]],
    course_id: str = "",
    chapter_id: str = "",
    storage_root: str | Path | None = None,
) -> dict[str, Any]:
    if not answers:
        raise QuizSubmissionInvalid("answers are required")
    manager = LearningArchiveManager(storage_root)
    normalized_answers = []
    submitted_at = datetime.now(timezone.utc).isoformat()
    for raw_answer in answers:
        if not isinstance(raw_answer, dict):
            raise QuizSubmissionInvalid("each answer must be an object")
        question_id = str(raw_answer.get("question_id") or raw_answer.get("item_id") or "").strip()
        if not question_id:
            raise QuizSubmissionInvalid("question_id is required for each answer")
        grading = raw_answer.get("grading_result")
        if not isinstance(grading, dict):
            grading = grade_saved_quiz_answer(
                user_id=user_id,
                artifact_id=artifact_id,
                question_id=question_id,
                user_answer=raw_answer.get("user_answer"),
                storage_root=storage_root,
            )
        normalized_answers.append(_answer_record(raw_answer, grading, submitted_at=submitted_at))

    result = manager.save_quiz_attempt(user_id=user_id, artifact_id=artifact_id, answers=normalized_answers)
    row = manager.repository.get_generated_artifact(artifact_id, user_id=user_id) or {}
    resolved_course_id = str(course_id or row.get("course_id") or "")
    resolved_chapter_id = str(chapter_id or row.get("chapter_id") or "")
    return {
        **result,
        "feedback_source_type": "quiz_result",
        "feedback_source_ids": {
            "user_id": user_id,
            "course_id": resolved_course_id,
            "chapter_id": resolved_chapter_id,
            "artifact_id": artifact_id,
            "attempt_id": result["attempt_id"],
        },
    }


def grade_saved_quiz_answer(
    *,
    user_id: str,
    artifact_id: str,
    question_id: str,
    user_answer: Any,
    storage_root: str | Path | None = None,
) -> dict[str, Any]:
    question = load_saved_quiz_question(
        user_id=user_id,
        artifact_id=artifact_id,
        question_id=question_id,
        storage_root=storage_root,
    )
    if question is None:
        raise QuizQuestionNotFound(question_id)
    return grade_quiz_answer({"question": question, "user_answer": user_answer})


def load_saved_quiz_question(
    *,
    user_id: str,
    artifact_id: str,
    question_id: str,
    storage_root: str | Path | None = None,
) -> dict[str, Any] | None:
    manager = LearningArchiveManager(storage_root)
    folder = manager._question_artifact_folder_for_existing(user_id=user_id, artifact_id=artifact_id)
    questions_path = folder / "questions.json"
    if not questions_path.exists():
        return None
    try:
        data = json.loads(questions_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return None
    wanted = _normalize_id(question_id)
    for item in items:
        if not isinstance(item, dict):
            continue
        candidates = [
            item.get("question_id"),
            item.get("id"),
            item.get("item_id"),
            item.get("sequence"),
        ]
        if any(_normalize_id(candidate) == wanted for candidate in candidates):
            return item
    return None


def grade_quiz_answer(payload: dict[str, Any]) -> dict[str, Any]:
    question = payload.get("question") if isinstance(payload.get("question"), dict) else payload
    if not isinstance(question, dict):
        question = {}
    question_type = _question_type(question, payload)
    max_score = _max_score(question, payload)
    user_answer = payload.get("user_answer")

    if question_type == "single_choice":
        return _grade_objective(question, user_answer, max_score=max_score, method="objective_choice_v1")
    if question_type == "true_false":
        return _grade_true_false(question, user_answer, max_score=max_score)
    if question_type == "cloze":
        return _grade_cloze(question, user_answer, max_score=max_score)
    if question_type == "short_answer":
        return _grade_short_answer(question, user_answer, max_score=max_score)

    result = _base_result(question, question_type, max_score=max_score)
    result.update(
        {
            "grading_method": "unsupported_question_type",
            "grader_confidence": 0.0,
            "feedback": f"暂不支持 {question_type} 题型的自动评分。",
        }
    )
    return result


def _answer_record(raw_answer: dict[str, Any], grading: dict[str, Any], *, submitted_at: str) -> dict[str, Any]:
    question_id = str(grading.get("question_id") or raw_answer.get("question_id") or raw_answer.get("item_id") or "")
    score = float(grading.get("earned_score") or 0.0)
    max_score = float(grading.get("max_score") or raw_answer.get("possible") or 1.0)
    return {
        "item_id": question_id,
        "question_id": question_id,
        "question_type": str(grading.get("question_type") or raw_answer.get("question_type") or ""),
        "user_answer": raw_answer.get("user_answer"),
        "is_correct": bool(grading.get("is_correct")),
        "score": score,
        "possible": max_score,
        "max_score": max_score,
        "feedback": str(grading.get("feedback") or ""),
        "grading_method": str(grading.get("grading_method") or ""),
        "grader_confidence": grading.get("grader_confidence"),
        "key_point_coverage": grading.get("key_point_coverage"),
        "semantic_similarity": grading.get("semantic_similarity"),
        "matched_key_points": _string_list(grading.get("matched_key_points")),
        "missed_key_points": _string_list(grading.get("missed_key_points")),
        "rubric_point_scores": grading.get("rubric_point_scores") or [],
        "capability_dimension": str(grading.get("capability_dimension") or ""),
        "knowledge_points": _string_list(grading.get("knowledge_points")),
        "core_exam_points": _string_list(grading.get("core_exam_points")),
        "grading_result": grading,
        "submitted_at": submitted_at,
    }


def _grade_objective(question: dict[str, Any], user_answer: Any, *, max_score: float, method: str) -> dict[str, Any]:
    result = _base_result(question, _question_type(question, {}), max_score=max_score)
    refs = {_compact_text(answer) for answer in _answer_candidates(question)}
    is_correct = bool(refs) and _compact_text(user_answer) in refs
    result.update(
        {
            "earned_score": max_score if is_correct else 0.0,
            "is_correct": is_correct,
            "grading_method": method,
            "grader_confidence": 1.0,
            "feedback": "回答正确。" if is_correct else "回答不正确，请回看本题对应知识点。",
        }
    )
    return result


def _grade_true_false(question: dict[str, Any], user_answer: Any, *, max_score: float) -> dict[str, Any]:
    normalized_user = _true_false_value(user_answer)
    normalized_refs = {_true_false_value(answer) for answer in _answer_candidates(question)}
    is_correct = normalized_user is not None and normalized_user in normalized_refs
    result = _base_result(question, "true_false", max_score=max_score)
    result.update(
        {
            "earned_score": max_score if is_correct else 0.0,
            "is_correct": is_correct,
            "grading_method": "objective_true_false_v1",
            "grader_confidence": 1.0,
            "feedback": "判断正确。" if is_correct else "判断不正确，请对照概念边界重新确认。",
        }
    )
    return result


def _grade_cloze(question: dict[str, Any], user_answer: Any, *, max_score: float) -> dict[str, Any]:
    answer = _compact_text(user_answer)
    candidates = [_compact_text(item) for item in _answer_candidates(question)]
    matched = bool(answer) and any(_cloze_equal(answer, candidate) for candidate in candidates if candidate)
    result = _base_result(question, "cloze", max_score=max_score)
    result.update(
        {
            "earned_score": max_score if matched else 0.0,
            "is_correct": matched,
            "grading_method": "deterministic_cloze_v1",
            "grader_confidence": 1.0 if matched else 0.9,
            "key_point_coverage": 1.0 if matched else 0.0,
            "matched_key_points": _core_points(question) if matched else [],
            "missed_key_points": [] if matched else _core_points(question),
            "feedback": "填空正确。" if matched else "填空答案未匹配标准答案或可接受别名。",
        }
    )
    return result


def _grade_short_answer(question: dict[str, Any], user_answer: Any, *, max_score: float) -> dict[str, Any]:
    result = _base_result(question, "short_answer", max_score=max_score)
    key_points = _rubric_key_points(question)
    if not key_points:
        result.update(
            {
                "grading_method": "manual_review_required_v1",
                "grader_confidence": 0.0,
                "feedback": "本题缺少可计算评分细则，需要人工或LLM兜底评分。",
            }
        )
        return result

    answer = str(user_answer or "")
    matched: list[str] = []
    missed: list[str] = []
    point_scores: list[dict[str, Any]] = []
    earned = 0.0
    total_rubric_score = sum(float(item["points"]) for item in key_points) or max_score
    scale = max_score / total_rubric_score if total_rubric_score else 1.0
    for item in key_points:
        description = str(item["description"])
        point_value = float(item["points"]) * scale
        covered = _key_point_covered(answer, description)
        if covered:
            matched.append(description)
            earned += point_value
        else:
            missed.append(description)
        point_scores.append(
            {
                "key_point": description,
                "max_score": round(point_value, 4),
                "earned_score": round(point_value if covered else 0.0, 4),
                "covered": covered,
            }
        )

    earned = round(min(max_score, earned), 4)
    coverage = round(earned / max_score, 4) if max_score else 0.0
    result.update(
        {
            "earned_score": earned,
            "is_correct": coverage >= 0.8,
            "grading_method": "rubric_keypoint_v1",
            "grader_confidence": 0.85 if answer.strip() else 1.0,
            "key_point_coverage": coverage,
            "matched_key_points": matched,
            "missed_key_points": missed,
            "rubric_point_scores": point_scores,
            "feedback": _short_answer_feedback(matched, missed),
        }
    )
    return result


def _base_result(question: dict[str, Any], question_type: str, *, max_score: float) -> dict[str, Any]:
    return {
        "question_id": str(
            question.get("question_id") or question.get("id") or question.get("item_id") or question.get("sequence") or ""
        ),
        "question_type": question_type,
        "earned_score": 0.0,
        "max_score": max_score,
        "is_correct": False,
        "grading_method": "",
        "semantic_similarity": None,
        "key_point_coverage": 0.0,
        "grader_confidence": 0.0,
        "feedback": "",
        "matched_key_points": [],
        "missed_key_points": [],
        "grading_version": GRADING_VERSION,
        "factuality_score": None,
        "contradictions": [],
        "safety_critical_error": False,
        "rubric_point_scores": [],
        "capability_dimension": str(question.get("capability_dimension") or ""),
        "knowledge_points": _string_list(question.get("knowledge_points")),
        "core_exam_points": _core_points(question),
    }


def _question_type(question: dict[str, Any], payload: dict[str, Any]) -> str:
    return str(question.get("question_type") or question.get("type") or payload.get("question_type") or "").strip()


def _max_score(question: dict[str, Any], payload: dict[str, Any]) -> float:
    for value in (payload.get("max_score"), question.get("max_score"), question.get("points")):
        try:
            score = float(value)
        except (TypeError, ValueError):
            continue
        if score > 0:
            return score
    key_points = _rubric_key_points(question)
    if key_points:
        total = sum(float(item["points"]) for item in key_points)
        if total > 0:
            return total
    return 1.0


def _answer_candidates(question: dict[str, Any]) -> list[Any]:
    values: list[Any] = []
    for key in ("reference_answer", "answer", "correct_answer"):
        if key in question:
            values.extend(_as_list(question.get(key)))
    for key in ("answer_aliases", "acceptable_answers", "aliases"):
        values.extend(_as_list(question.get(key)))
    return values


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _compact_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    return re.sub(r"[\s，。、“”‘’：:；;,.!?！？（）()\[\]{}<>《》/\\|_-]+", "", text)


def _cloze_equal(user_answer: str, reference_answer: str) -> bool:
    if user_answer == reference_answer:
        return True
    suffixes = ("轴", "指令", "代码")
    normalized_refs = {reference_answer}
    for suffix in suffixes:
        if reference_answer.endswith(suffix):
            normalized_refs.add(reference_answer[: -len(suffix)])
    return user_answer in normalized_refs


def _true_false_value(value: Any) -> bool | None:
    normalized = _compact_text(value)
    if normalized in {"a", "true", "t", "yes", "y", "1", "正确", "对", "是", "√"}:
        return True
    if normalized in {"b", "false", "f", "no", "n", "0", "错误", "错", "否", "×", "x"}:
        return False
    return None


def _rubric_key_points(question: dict[str, Any]) -> list[dict[str, Any]]:
    rubric = question.get("scoring_rubric")
    raw_points = rubric.get("key_points") if isinstance(rubric, dict) else None
    if not isinstance(raw_points, list):
        return []
    result = []
    for item in raw_points:
        if isinstance(item, dict):
            description = str(item.get("description") or item.get("key_point") or "").strip()
            points = item.get("points", 1)
        else:
            description = str(item or "").strip()
            points = 1
        if not description:
            continue
        try:
            point_value = float(points)
        except (TypeError, ValueError):
            point_value = 1.0
        result.append({"description": description, "points": max(point_value, 0.0)})
    return result


def _key_point_covered(answer: str, description: str) -> bool:
    answer_text = _compact_text(answer)
    if not answer_text:
        return False
    key_phrases = _key_phrases(description)
    if not key_phrases:
        return False
    matched = sum(1 for phrase in key_phrases if _phrase_covered(answer_text, phrase))
    return matched / len(key_phrases) >= 0.5


def _phrase_covered(answer_text: str, phrase: str) -> bool:
    if phrase in answer_text:
        return True
    if len(phrase) < 4:
        return False
    window_size = min(len(answer_text), max(len(phrase) + 2, 4))
    for start in range(0, max(len(answer_text) - window_size + 1, 1)):
        window = answer_text[start : start + window_size]
        if SequenceMatcher(None, phrase, window).ratio() >= 0.78:
            return True
    return False


def _key_phrases(text: str) -> list[str]:
    compact = _compact_text(text)
    phrases: list[str] = []
    for chunk in re.split(r"(?:并|和|与|及|、)", unicodedata.normalize("NFKC", text)):
        normalized = _compact_text(chunk)
        if len(normalized) >= 2:
            phrases.append(normalized)
    if compact and compact not in phrases and len(phrases) <= 1:
        phrases.append(compact)
    terms = re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z][a-zA-Z0-9]*\d*", text)
    for term in terms:
        normalized = _compact_text(term)
        if normalized == compact and len(phrases) > 1:
            continue
        if len(normalized) >= 2 and normalized not in phrases:
            phrases.append(normalized)
    return phrases


def _short_answer_feedback(matched: list[str], missed: list[str]) -> str:
    if not missed:
        return "要点覆盖完整。"
    if not matched:
        return "答案尚未覆盖评分细则中的关键要点。"
    return "已覆盖部分要点，建议补充：" + "；".join(missed)


def _core_points(question: dict[str, Any]) -> list[str]:
    return _string_list(question.get("core_exam_points") or question.get("core_points"))


def _string_list(value: Any) -> list[str]:
    result = []
    for item in _as_list(value):
        text = str(item or "").strip()
        if text:
            result.append(text)
    return result


def _normalize_id(value: Any) -> str:
    return str(value or "").strip()
