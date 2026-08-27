from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agent.node.node_logging import log_node_runtime
from agent.state import OverallState
from agent.storage_layout import safe_segment
from agent.tools.feedback_context_tools import load_qa_feedback_context, load_quiz_feedback_context


@log_node_runtime("quiz_feedback_context_loader_node")
def quiz_feedback_context_loader_node(state: OverallState) -> OverallState:
    try:
        load_result = load_quiz_feedback_context(
            user_id=str(state.get("user_id") or ""),
            course_id=str(state.get("course_id") or ""),
            chapter_id=str(state.get("chapter_id") or ""),
            artifact_id=str(state.get("artifact_id") or state.get("question_artifact_id") or ""),
            attempt_id=str(state.get("attempt_id") or ""),
            question_scope=str(state.get("question_scope") or "path_generated"),
            storage_root=state.get("_storage_root"),
        )
    except ValueError as exc:
        load_result = _invalid_context_result("quiz_result", exc)
    if load_result.get("feedback_context_load_result", {}).get("status") != "success":
        return {
            **load_result,
            "feedback_result": {
                "status": "no_update",
                "feedback_type": "quiz_result",
                "message": "quiz feedback context could not be loaded",
            },
            "profile_update_result": {"accepted": False, "reason": "feedback_context_load_failed"},
        }

    suggestions = _quiz_profile_suggestions(
        user_id=str(state.get("user_id") or ""),
        course_id=str(state.get("course_id") or ""),
        chapter_id=str(state.get("chapter_id") or ""),
        context=load_result.get("feedback_context") or {},
    )
    packet = _quiz_profile_evidence_packet(state, load_result, suggestions)
    return {
        **load_result,
        "profile_update_suggestions": suggestions,
        "profile_evidence_packet": packet,
        "profile_update_result": {"accepted": False, "reason": "pending_profile_assessment_review"},
        "feedback_assessment": suggestions["feedback_assessment"],
        "feedback_result": {
            "status": "pending_review",
            "feedback_type": "quiz_result",
            "message": "built profile evidence packet from quiz attempt evidence",
            "proposed_metrics": len(suggestions.get("metric_patches") or []),
            "proposed_capability_evidence": len(suggestions.get("capability_evidence") or []),
            "proposed_knowledge_gaps": len(suggestions.get("knowledge_gap_patches") or []),
            "proposed_learning_progress": len(suggestions.get("progress_patches") or []),
        },
    }


@log_node_runtime("qa_feedback_context_loader_node")
def qa_feedback_context_loader_node(state: OverallState) -> OverallState:
    try:
        return load_qa_feedback_context(
            user_id=str(state.get("user_id") or ""),
            course_id=str(state.get("course_id") or ""),
            session_id=str(state.get("session_id") or state.get("qa_session_id") or ""),
            storage_root=state.get("_storage_root"),
        )
    except ValueError as exc:
        return _invalid_context_result("qa_dialogue", exc)


def _quiz_profile_suggestions(*, user_id: str, course_id: str, chapter_id: str, context: dict[str, Any]) -> dict[str, Any]:
    accuracy = _coerce_accuracy(context.get("accuracy"))
    capability_evidence = _capability_evidence_from_quiz_context(
        course_id=course_id,
        chapter_id=chapter_id,
        context=context,
    )
    gap_patches = _quiz_gap_patches_from_context(
        user_id=user_id,
        course_id=course_id,
        chapter_id=chapter_id,
        context=context,
    )
    return {
        "source_node": "quiz_feedback_context_loader_node",
        "feedback_assessment": {
            "feedback_type": "quiz_result",
            "confidence": 1.0,
            "rationale": "deterministic update from stored quiz answers and question knowledge points",
        },
        "metric_patches": [
            {
                "field": "theory_score",
                "value": round(accuracy * 100),
                "reason": "quiz attempt accuracy",
            }
        ],
        "capability_evidence": capability_evidence,
        "knowledge_gap_patches": gap_patches,
        "progress_patches": [
            {
                "course_id": course_id,
                "chapter_id": chapter_id,
                "status": "completed" if accuracy >= 0.8 else "needs_review",
                "completion_rate": accuracy,
            }
        ],
    }


def _invalid_context_result(source_type: str, exc: ValueError) -> dict[str, Any]:
    return {
        "feedback_source_type": source_type,
        "feedback_context_load_result": {
            "status": "invalid",
            "missing_files": [],
            "mismatched_fields": [_invalid_field_from_error(str(exc))],
            "error": str(exc),
        },
    }


def _quiz_profile_evidence_packet(
    state: OverallState,
    load_result: dict[str, Any],
    suggestions: dict[str, Any],
) -> dict[str, Any]:
    source_ids = load_result.get("feedback_source_ids") if isinstance(load_result.get("feedback_source_ids"), dict) else {}
    attempt_id = str(source_ids.get("attempt_id") or state.get("attempt_id") or "")
    packet_id = str(state.get("request_id") or attempt_id or source_ids.get("artifact_id") or "quiz_result")
    context = load_result.get("feedback_context") if isinstance(load_result.get("feedback_context"), dict) else {}
    return {
        "packet_id": packet_id,
        "packet_type": "profile_evidence_packet",
        "source_type": "quiz_result",
        "source_node": "quiz_feedback_context_loader_node",
        "user_id": str(source_ids.get("user_id") or state.get("user_id") or ""),
        "course_id": str(source_ids.get("course_id") or state.get("course_id") or ""),
        "chapter_id": str(source_ids.get("chapter_id") or state.get("chapter_id") or ""),
        "artifact_id": str(source_ids.get("artifact_id") or state.get("artifact_id") or state.get("question_artifact_id") or ""),
        "attempt_id": attempt_id,
        "question_scope": str(state.get("question_scope") or "path_generated"),
        "overall_result": "quiz_evidence_proposed",
        "confidence": 1.0,
        "accuracy": context.get("accuracy"),
        "student_visible_feedback": "",
        "proposed_profile_changes": suggestions,
        "artifact_refs": load_result.get("feedback_context_paths") or {},
    }


def _invalid_field_from_error(message: str) -> str:
    if ":" not in message:
        return "unknown"
    return message.split(":", 1)[0].replace("unsafe", "").strip() or "unknown"


def _coerce_accuracy(value: Any) -> float:
    try:
        return min(max(float(value), 0.0), 1.0)
    except (TypeError, ValueError):
        return 0.0


def _gap_id(user_id: str, course_id: str, chapter_id: str, concept: str) -> str:
    return "gap_" + "_".join(safe_segment(part) for part in (user_id, course_id, chapter_id, concept) if part)


def _capability_evidence_from_quiz_context(*, course_id: str, chapter_id: str, context: dict[str, Any]) -> list[dict[str, Any]]:
    question_set = context.get("question_set") if isinstance(context.get("question_set"), dict) else {}
    questions = {_question_id(item): item for item in _question_items(question_set) if _question_id(item)}
    attempt = context.get("quiz_attempt") if isinstance(context.get("quiz_attempt"), dict) else {}
    attempt_id = str(attempt.get("attempt_id") or "").strip()
    if not attempt_id:
        return []
    answers = [item for item in context.get("answers") or [] if isinstance(item, dict)]
    evidence = []
    for index, answer in enumerate(answers, start=1):
        question_id = str(answer.get("item_id") or answer.get("question_id") or "").strip()
        question = questions.get(question_id)
        if not question:
            continue
        knowledge_point = _primary_knowledge_point(answer, question)
        dimension, dimension_source = _capability_dimension(answer, question)
        possible = _possible_points(question, answer)
        earned = _earned_points(answer, possible)
        item = {
            "id": f"{attempt_id}-{question_id or index}",
            "attemptId": attempt_id,
            "sourceType": "quiz",
            "dimension": dimension,
            "topic": f"{course_id}:{chapter_id}",
            "knowledgePoint": knowledge_point,
            "knowledgePointId": _knowledge_point_id_from_answer_or_question(course_id, chapter_id, answer, question, knowledge_point),
            "correct": bool(answer.get("is_correct")),
            "earned": earned,
            "possible": possible,
            "difficulty": _difficulty(answer.get("difficulty") or question.get("difficulty")),
            "occurredAt": str(attempt.get("submitted_at") or attempt.get("created_at") or _now()),
            "sourceRefs": _string_list(answer.get("source_refs") or question.get("source_refs")),
            "ragChunkIds": _string_list(answer.get("rag_chunk_ids") or question.get("rag_chunk_ids")),
            "questionType": str(answer.get("question_type") or question.get("question_type") or question.get("type") or "single_choice"),
            "attemptNumber": int(attempt.get("attempt_number") or answer.get("attempt_number") or 1),
            "itemRevision": str(answer.get("item_revision") or question.get("revision") or question_id or index),
            "dimensionSource": dimension_source,
            "questionGrounded": bool(answer.get("source_refs") or answer.get("rag_chunk_ids") or question.get("source_refs") or question.get("rag_chunk_ids")),
            "reviewStatus": _review_status(answer),
            "chapterId": chapter_id,
            "objectiveIds": _string_list(answer.get("objective_ids") or question.get("objective_ids")),
            "coreExamPoints": _core_exam_points(answer, question),
        }
        item.update(_grading_evidence_fields(answer))
        evidence.append(item)
    return evidence


def _quiz_gap_patches_from_context(*, user_id: str, course_id: str, chapter_id: str, context: dict[str, Any]) -> list[dict[str, Any]]:
    question_set = context.get("question_set") if isinstance(context.get("question_set"), dict) else {}
    questions = {_question_id(item): item for item in _question_items(question_set) if _question_id(item)}
    answers = [item for item in context.get("answers") or [] if isinstance(item, dict)]
    patches: dict[str, dict[str, Any]] = {}
    for answer in answers:
        question_id = str(answer.get("item_id") or answer.get("question_id") or "").strip()
        question = questions.get(question_id, {})
        if bool(answer.get("is_correct")):
            for concept in _gap_candidate_concepts(answer, question):
                patch = {
                    "gap_id": _gap_id(user_id, course_id, chapter_id, concept),
                    "concept": concept,
                    "chapter_id": chapter_id,
                    "category": str(_capability_dimension(answer, question)[0] or ""),
                    "severity": "low",
                    "evidence": f"quiz attempt answered related item correctly: {question_id}",
                    "status": "resolved",
                    "source": "quiz_result",
                }
                patches.setdefault(patch["gap_id"], patch)
            continue

        missed_key_points = _missed_key_points(answer)
        for concept in missed_key_points:
            patch = {
                "gap_id": _gap_id(user_id, course_id, chapter_id, concept),
                "concept": concept,
                "chapter_id": chapter_id,
                "category": str(_capability_dimension(answer, question)[0] or ""),
                "severity": "high",
                "evidence": f"missed_key_points: {concept}; question_id={question_id}; feedback={answer.get('feedback') or ''}",
                "status": "open",
                "source": "quiz_result",
                "recommended_actions": [f"针对“{concept}”进行错题复盘和同类题练习"],
            }
            patches[patch["gap_id"]] = patch

        for concept in _gap_candidate_concepts(answer, question):
            patch = {
                "gap_id": _gap_id(user_id, course_id, chapter_id, concept),
                "concept": concept,
                "chapter_id": chapter_id,
                "category": str(_capability_dimension(answer, question)[0] or ""),
                "severity": "medium",
                "evidence": f"quiz answer incorrect; question_id={question_id}; feedback={answer.get('feedback') or ''}",
                "status": "open",
                "source": "quiz_result",
            }
            patches.setdefault(patch["gap_id"], patch)
    return list(patches.values())


def _question_items(question_set: dict[str, Any]) -> list[dict[str, Any]]:
    value = question_set.get("items") or question_set.get("questions")
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _question_id(question: dict[str, Any]) -> str:
    return str(question.get("id") or question.get("item_id") or question.get("question_id") or "").strip()


def _primary_knowledge_point(answer: dict[str, Any], question: dict[str, Any]) -> str:
    points = answer.get("knowledge_points") or question.get("knowledge_points") or question.get("core_points")
    if isinstance(points, list):
        for point in points:
            if isinstance(point, dict):
                name = str(point.get("name") or point.get("id") or "").strip()
            else:
                name = str(point).strip()
            if name:
                return name
    return str(answer.get("knowledge_point") or question.get("knowledge_point") or question.get("stem") or question.get("question_text") or "未标注知识点")[:120]


def _capability_dimension(answer: dict[str, Any], question: dict[str, Any]) -> tuple[str, str]:
    declared = _declared_dimension(
        answer.get("capability_dimension")
        or answer.get("capabilityDimension")
        or question.get("capability_dimension")
        or question.get("capabilityDimension")
    )
    if declared:
        return declared, "declared"
    text = _normalized_text(
        " ".join(
            str(answer.get(key) or question.get(key) or "")
            for key in ("stem", "question_text", "explanation", "feedback", "user_answer")
        )
    )
    keyword_map = {
        "safety": ("安全", "急停", "防护", "危险", "违规"),
        "programming": ("编程", "程序", "g代码", "m代码", "g02", "g03", "刀补", "仿真"),
        "process_planning": ("工艺", "工序", "装夹", "切削参数", "工艺路线"),
        "machining_operation": ("操作", "回零", "对刀", "试运行", "自动加工"),
        "quality_control": ("测量", "检测", "精度", "误差", "公差", "质量"),
        "maintenance": ("维护", "保养", "报警", "故障", "润滑"),
        "advanced_manufacturing": ("多轴", "五轴", "车铣复合", "智能制造"),
    }
    for dimension, keywords in keyword_map.items():
        if any(_normalized_text(keyword) in text for keyword in keywords):
            return dimension, "keyword"
    return "foundations", "fallback"


def _declared_dimension(value: Any) -> str:
    token = str(value or "").strip()
    aliases = {
        "theory": "foundations",
        "foundations": "foundations",
        "基础理论": "foundations",
        "基础识图": "foundations",
        "safety": "safety",
        "安全": "safety",
        "programming": "programming",
        "数控编程": "programming",
        "process_planning": "process_planning",
        "工艺规划": "process_planning",
        "machining_operation": "machining_operation",
        "operation": "machining_operation",
        "quality_control": "quality_control",
        "maintenance": "maintenance",
        "advanced_manufacturing": "advanced_manufacturing",
    }
    normalized = token.lower().replace("-", "_").replace(" ", "_")
    return aliases.get(normalized) or aliases.get(token) or ""


def _knowledge_point_id(course_id: str, chapter_id: str, knowledge_point: str) -> str:
    return ".".join(safe_segment(part) for part in (course_id, chapter_id, knowledge_point) if safe_segment(part))


def _knowledge_point_id_from_answer_or_question(
    course_id: str,
    chapter_id: str,
    answer: dict[str, Any],
    question: dict[str, Any],
    knowledge_point: str,
) -> str:
    for source in (answer, question):
        points = source.get("knowledge_points")
        if not isinstance(points, list):
            continue
        for point in points:
            if isinstance(point, dict):
                point_id = str(point.get("id") or point.get("knowledge_point_id") or "").strip()
                name = str(point.get("name") or "").strip()
                if point_id and (not name or name == knowledge_point):
                    return point_id
    return _knowledge_point_id(course_id, chapter_id, knowledge_point)


def _possible_points(question: dict[str, Any], answer: dict[str, Any]) -> float:
    for value in (answer.get("possible"), question.get("points")):
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return 1.0


def _earned_points(answer: dict[str, Any], possible: float) -> float:
    if "score" in answer:
        try:
            return min(max(float(answer.get("score")), 0.0), possible)
        except (TypeError, ValueError):
            pass
    return possible if answer.get("is_correct") else 0.0


def _grading_evidence_fields(answer: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for source_key, target_key in (
        ("grading_method", "gradingMethod"),
        ("rubric_version", "rubricVersion"),
    ):
        value = str(answer.get(source_key) or "").strip()
        if value:
            result[target_key] = value
    grading_result = answer.get("grading_result") if isinstance(answer.get("grading_result"), dict) else {}
    if not result.get("rubricVersion") and str(grading_result.get("rubric_version") or "").strip():
        result["rubricVersion"] = str(grading_result.get("rubric_version")).strip()
    for source_key, target_key in (
        ("semantic_score", "semanticScore"),
        ("key_point_score", "keyPointScore"),
        ("grader_confidence", "graderConfidence"),
    ):
        value = _optional_unit(answer.get(source_key))
        if value is not None:
            result[target_key] = value
    key_point_coverage = answer.get("key_point_coverage")
    if isinstance(key_point_coverage, dict):
        result["keyPointCoverage"] = key_point_coverage
    if grading_result:
        result["gradingResult"] = grading_result
    return result


def _optional_unit(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return min(max(float(value), 0.0), 1.0)
    except (TypeError, ValueError):
        return None


def _core_exam_points(answer: dict[str, Any], question: dict[str, Any]) -> list[str]:
    return _string_list(answer.get("core_exam_points") or question.get("core_exam_points"))


def _missed_key_points(answer: dict[str, Any]) -> list[str]:
    grading_result = answer.get("grading_result") if isinstance(answer.get("grading_result"), dict) else {}
    coverage = answer.get("key_point_coverage") if isinstance(answer.get("key_point_coverage"), dict) else {}
    return _string_list(grading_result.get("missed_key_points") or coverage.get("missed"))


def _gap_candidate_concepts(answer: dict[str, Any], question: dict[str, Any]) -> list[str]:
    concepts = []
    concepts.extend(_knowledge_point_names(answer.get("knowledge_points") or question.get("knowledge_points") or question.get("core_points")))
    concepts.extend(_core_exam_points(answer, question))
    return _dedupe(concepts)


def _knowledge_point_names(value: Any) -> list[str]:
    result = []
    if not isinstance(value, list):
        return result
    for item in value:
        if isinstance(item, dict):
            text = str(item.get("name") or item.get("id") or "").strip()
        else:
            text = str(item).strip()
        if text:
            result.append(text)
    return result


def _dedupe(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _review_status(answer: dict[str, Any]) -> str:
    if answer.get("review_status") in {"auto_verified", "pending_review", "reviewed", "rejected"}:
        return str(answer.get("review_status"))
    if answer.get("grading_method") or answer.get("grader_confidence") is not None:
        confidence = _optional_unit(answer.get("grader_confidence"))
        return "auto_verified" if confidence is not None and confidence >= 0.8 else "pending_review"
    return "auto_verified"


def _difficulty(value: Any) -> str:
    text = _normalized_text(value)
    if text in {"hard", "困难", "较难", "进阶", "advanced"}:
        return "hard"
    if text in {"medium", "normal", "中等", "中级"}:
        return "medium"
    return "easy"


def _string_list(value: Any) -> list[str]:
    return [str(item).strip() for item in value if str(item).strip()] if isinstance(value, list) else []


def _normalized_text(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "").replace("-", "_")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _wrong_evidence(concept: str, result: dict[str, Any]) -> str:
    examples = [str(item) for item in result.get("evidence") or [] if str(item).strip()]
    if examples:
        return f"{concept} wrong_count={int(result.get('wrong_count') or 0)}; examples: {'; '.join(examples[:3])}"
    return f"{concept} wrong_count={int(result.get('wrong_count') or 0)}"
