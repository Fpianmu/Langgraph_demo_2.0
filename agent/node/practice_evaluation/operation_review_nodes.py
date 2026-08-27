from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from agent.node.node_logging import log_node_runtime
from agent.rag.config import RagConfig
from agent.state import OverallState
from agent.tools.course_resource_tools import load_operation_task_bundle, load_workpiece_standard_spec
from agent.tools.operation_review_tools import (
    save_operation_submission,
    write_operation_review_json,
    write_operation_review_markdown,
)
from agent.tools.operation_submission_tools import load_operation_submission
from agent.tools.profile.capability_assessment_store import CAPABILITY_DIMENSION_IDS


load_dotenv(override=True)

_review_model: Any | None = None
_vl_model: Any | None = None


@log_node_runtime("workpiece_standard_loader_node")
def workpiece_standard_loader_node(state: OverallState) -> OverallState:
    course_id = str(state.get("course_id") or "cnc_lathe")
    chapter_id = str(state.get("chapter_id") or "")
    task_id = str(state.get("task_id") or "")
    workpiece_id = str(state.get("workpiece_id") or "")
    resource_root = state.get("_course_resource_root")

    task_bundle = load_operation_task_bundle(course_id, chapter_id, task_id, resource_root=resource_root)
    if not workpiece_id:
        workpiece_id = str(task_bundle.get("workpiece_id") or "")
    standard_spec = load_workpiece_standard_spec(course_id, workpiece_id, resource_root=resource_root)
    review_rules = _read_task_json_asset(task_bundle.get("review_rules"))
    return {
        "operation_review_intent": "submit_review",
        "operation_task_bundle": task_bundle,
        "standard_workpiece_spec": standard_spec,
        "review_rules": review_rules,
        "workpiece_id": workpiece_id,
        "static_task_ref": _static_task_ref(task_bundle),
    }


@log_node_runtime("operation_submission_loader_node")
def operation_submission_loader_node(state: OverallState) -> OverallState:
    if _uploaded_images(state) and _measurement_params(state):
        return {
            "operation_submission_load_result": {
                "status": "skipped",
                "reason": "state_payload_present",
            }
        }

    required_ids = ["user_id", "course_id", "chapter_id", "task_id", "submission_id"]
    missing_ids = [field for field in required_ids if not str(state.get(field) or "").strip()]
    if missing_ids:
        return {
            "operation_submission_load_result": {
                "status": "not_found",
                "reason": "missing_required_ids",
                "missing_ids": missing_ids,
            }
        }

    return load_operation_submission(
        user_id=str(state.get("user_id") or ""),
        course_id=str(state.get("course_id") or ""),
        chapter_id=str(state.get("chapter_id") or ""),
        task_id=str(state.get("task_id") or ""),
        submission_id=str(state.get("submission_id") or ""),
        storage_root=state.get("_storage_root"),
    )


@log_node_runtime("submission_validation_node")
def submission_validation_node(state: OverallState) -> OverallState:
    uploaded_images = _uploaded_images(state)
    measurement_params = _measurement_params(state)
    required_dimensions = _required_dimension_names(state.get("standard_workpiece_spec"))
    missing_fields = []
    if not str(state.get("user_id") or "").strip():
        missing_fields.append("user_id")
    if not str(state.get("task_id") or "").strip():
        missing_fields.append("task_id")
    if not uploaded_images:
        missing_fields.append("uploaded_images")
    load_result = state.get("operation_submission_load_result")
    if isinstance(load_result, dict) and load_result.get("status") in {"not_found", "invalid"}:
        missing_fields.append("operation_submission_load_result")
    invalid_images = _invalid_local_images(uploaded_images)
    missing_fields.extend(
        f"uploaded_images.{item['name']}.missing_file"
        for item in invalid_images
        if item.get("reason") == "local_file_not_found"
    )
    missing_fields.extend(
        f"uploaded_images.{item['name']}.path"
        for item in invalid_images
        if item.get("reason") == "missing_image_reference"
    )
    missing_measurements = [name for name in required_dimensions if name not in measurement_params]
    missing_fields.extend(f"measurement_params.{name}" for name in missing_measurements)

    status = "valid" if not missing_fields else "need_resubmission"
    submission_id = str(state.get("submission_id") or _default_submission_id())
    paths = save_operation_submission(
        user_id=str(state.get("user_id") or "default_user"),
        course_id=str(state.get("course_id") or "cnc_lathe"),
        chapter_id=str(state.get("chapter_id") or ""),
        task_id=str(state.get("task_id") or ""),
        workpiece_id=str(state.get("workpiece_id") or ""),
        submission_id=submission_id,
        uploaded_images=uploaded_images,
        measurement_params=measurement_params,
        static_task_ref=str(state.get("static_task_ref") or ""),
        storage_root=state.get("_storage_root"),
    )
    return {
        "submission_id": submission_id,
        "operation_review_paths": paths,
        "submission_validation_result": {
            "status": status,
            "missing_fields": missing_fields,
            "missing_measurements": missing_measurements,
            "invalid_images": invalid_images,
            "image_count": len(uploaded_images),
        },
    }


@log_node_runtime("vl_analysis_node")
def vl_analysis_node(state: OverallState) -> OverallState:
    if _validation_needs_resubmission(state):
        result = {"status": "skipped", "reason": "submission_validation_failed", "findings": []}
        _persist_json_if_path(state, "vl_analysis_result", result)
        return {"vl_analysis_result": result}

    raw = _invoke_vl_model(state)
    data = _load_json_object(raw)
    findings = data.get("findings") if isinstance(data.get("findings"), list) else []
    result = {
        "status": "success",
        "model": str(os.getenv("QWEN_VL_MODEL", "qwen3-vl-plus")),
        "image_count": len(_uploaded_images(state)),
        "findings": [item for item in findings if isinstance(item, dict)],
        "overall_visual_status": str(data.get("overall_visual_status") or _overall_visual_status(findings)),
        "raw_output": raw,
    }
    _persist_json_if_path(state, "vl_analysis_result", result)
    return {"vl_analysis_result": result}


@log_node_runtime("measurement_compare_node")
def measurement_compare_node(state: OverallState) -> OverallState:
    measurement_params = _measurement_params(state)
    dimensions = _dimensions(state.get("standard_workpiece_spec"))
    results = []
    for item in dimensions:
        name = str(item.get("name") or "").strip()
        actual = _coerce_float(measurement_params.get(name))
        target = _coerce_float(item.get("target"))
        upper = _coerce_float(item.get("upper_tolerance"))
        lower = _coerce_float(item.get("lower_tolerance"))
        if actual is None or target is None or upper is None or lower is None:
            result = "missing" if actual is None else "invalid_standard"
            error = None
        else:
            error = round(actual - target, 6)
            result = "pass" if lower <= error <= upper else "fail"
        results.append(
            {
                "name": name,
                "display_name": item.get("display_name") or item.get("label") or name,
                "target": target,
                "actual": actual,
                "error": error,
                "upper_tolerance": upper,
                "lower_tolerance": lower,
                "unit": item.get("unit") or state.get("standard_workpiece_spec", {}).get("unit") or "",
                "importance": item.get("importance") or ("critical" if item.get("required", True) else "normal"),
                "required": bool(item.get("required", True)),
                "result": result,
            }
        )

    comparison = {
        "status": "success",
        "dimension_results": results,
        "dimension_pass_count": sum(1 for item in results if item["result"] == "pass"),
        "dimension_fail_count": sum(1 for item in results if item["result"] == "fail"),
        "dimension_missing_count": sum(1 for item in results if item["result"] == "missing"),
        "critical_fail_count": sum(
            1 for item in results if item["result"] in {"fail", "missing"} and item["importance"] == "critical"
        ),
    }
    _persist_json_if_path(state, "measurement_comparison_result", comparison)
    return {"measurement_comparison_result": comparison}


@log_node_runtime("operation_review_node")
def operation_review_node(state: OverallState) -> OverallState:
    decision = _rule_based_decision(state)
    llm_report = _invoke_review_llm(state, decision)
    result = {
        "status": "reviewed",
        **decision,
        "llm_report": llm_report,
        "measurement_comparison_result": state.get("measurement_comparison_result") or {},
        "vl_analysis_result": state.get("vl_analysis_result") or {},
    }
    suggestions = _profile_update_suggestions(state, result)
    _persist_json_if_path(state, "operation_review_result", result)
    _persist_report_if_path(state, _markdown_report(result))
    return {
        "rule_based_review_decision": decision,
        "operation_review_result": result,
        "operation_profile_update_suggestions": suggestions,
    }


@log_node_runtime("operation_profile_update_node")
def operation_profile_update_node(state: OverallState) -> OverallState:
    suggestions = state.get("operation_profile_update_suggestions") or {}
    review = state.get("operation_review_result") or {}
    packet_id = str(
        state.get("submission_id")
        or state.get("request_id")
        or review.get("decision_source")
        or ""
    )
    profile_evidence_packet = {
        "packet_id": packet_id or f"operation-{str(state.get('task_id') or 'task')}",
        "source_type": "practice",
        "user_id": str(state.get("user_id") or "default_user"),
        "course_id": str(state.get("course_id") or ""),
        "chapter_id": str(state.get("chapter_id") or ""),
        "task_id": str(state.get("task_id") or ""),
        "attempt_id": str(state.get("submission_id") or state.get("request_id") or packet_id or ""),
        "overall_result": str(review.get("final_result") or ""),
        "confidence": 0.95 if review.get("final_result") in {"pass", "pass_with_warning"} else 0.9,
        "proposed_profile_changes": suggestions,
        "artifact_refs": {
            "operation_review_paths": state.get("operation_review_paths") or {},
            "operation_review_result": state.get("operation_review_paths", {}).get("operation_review_result", ""),
            "llm_review_report": state.get("operation_review_paths", {}).get("llm_review_report", ""),
        },
    }
    return {
        "profile_evidence_packet": profile_evidence_packet,
        "operation_profile_update_result": {
            "accepted": False,
            "source": "operation_review",
            "review_status": "pending_profile_assessment_review" if suggestions else "no_valid_profile_changes",
            "suggestions": suggestions,
        }
    }


def _read_task_json_asset(asset: Any) -> dict[str, Any]:
    if not isinstance(asset, dict) or not asset.get("path"):
        return {}
    path = Path(str(asset["path"]))
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _static_task_ref(task_bundle: dict[str, Any]) -> str:
    path = str(task_bundle.get("task_manifest_path") or "")
    marker = "/course_resources/"
    normalized = path.replace("\\", "/")
    if marker in normalized:
        return "course_resources/" + normalized.split(marker, 1)[1]
    return normalized


def _uploaded_images(state: OverallState) -> list[dict[str, Any]]:
    value = state.get("uploaded_images")
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _measurement_params(state: OverallState) -> dict[str, Any]:
    value = state.get("measurement_params")
    return value if isinstance(value, dict) else {}


def _required_dimension_names(spec: Any) -> list[str]:
    return [str(item.get("name")) for item in _dimensions(spec) if item.get("required", True) and item.get("name")]


def _dimensions(spec: Any) -> list[dict[str, Any]]:
    if not isinstance(spec, dict):
        return []
    value = spec.get("dimensions") or spec.get("standard_dimensions")
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _validation_needs_resubmission(state: OverallState) -> bool:
    validation = state.get("submission_validation_result")
    return isinstance(validation, dict) and validation.get("status") == "need_resubmission"


def _invalid_local_images(uploaded_images: list[dict[str, Any]]) -> list[dict[str, Any]]:
    invalid = []
    for index, image in enumerate(uploaded_images):
        ref = str(image.get("path") or image.get("url") or "").strip()
        name = _image_field_name(image, index)
        if not ref:
            invalid.append({"index": index, "name": name, "path": ref, "reason": "missing_image_reference"})
            continue
        if re.match(r"^https?://", ref):
            continue
        path = _local_image_path(ref)
        if not path.exists() or not path.is_file():
            invalid.append({"index": index, "name": name, "path": ref, "reason": "local_file_not_found"})
    return invalid


def _image_field_name(image: dict[str, Any], index: int) -> str:
    raw = str(image.get("name") or f"image_{index + 1}").strip()
    return re.sub(r"[^0-9A-Za-z_\-.]+", "_", raw) or f"image_{index + 1}"


def _local_image_path(ref: str) -> Path:
    if ref.startswith("file://"):
        local_ref = ref[len("file://") :]
        if re.match(r"^/[A-Za-z]:", local_ref):
            local_ref = local_ref[1:]
        return Path(local_ref).expanduser()
    path = Path(ref).expanduser()
    return path if path.is_absolute() else path.resolve()


def _invoke_vl_model(state: OverallState) -> str:
    model = state.get("_vl_model") or _default_vl_model()
    prompt = json.dumps(
        {
            "task": "Inspect machining result images. Return JSON only.",
            "uploaded_images": _uploaded_images(state),
            "visual_checks": (state.get("standard_workpiece_spec") or {}).get("visual_checks") or [],
            "standard_images": (state.get("operation_task_bundle") or {}).get("standard_images") or [],
        },
        ensure_ascii=False,
    )
    response = model.invoke([_human_message(_vl_message_content(prompt, _uploaded_images(state)))])
    return str(getattr(response, "content", response))


def _default_vl_model() -> Any:
    global _vl_model
    if _vl_model is None:
        try:
            from langchain_community.chat_models.tongyi import ChatTongyi

            _vl_model = ChatTongyi(model_name=os.getenv("QWEN_VL_MODEL", "qwen3-vl-plus"))
        except Exception:
            _vl_model = _DashScopeVlModel()
    return _vl_model


class _DashScopeVlModel:
    def invoke(self, messages: Any) -> Any:
        import dashscope

        dashscope.api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("QWEN_API_KEY")
        content = getattr(messages[0], "content", messages) if messages else messages
        response = dashscope.MultiModalConversation.call(
            model=os.getenv("QWEN_VL_MODEL", "qwen3-vl-plus"),
            messages=[{"role": "user", "content": content}],
        )
        content = response.output.choices[0].message.content
        return type("Message", (), {"content": json.dumps(content, ensure_ascii=False)})()


def _overall_visual_status(findings: Any) -> str:
    if not isinstance(findings, list):
        return "unknown"
    results = {str(item.get("result") or "") for item in findings if isinstance(item, dict)}
    if "severe" in results or "fail" in results:
        return "severe"
    if "warning" in results:
        return "warning"
    if "pass" in results:
        return "pass"
    return "unknown"


def _coerce_float(value: Any) -> float | None:
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None


def _rule_based_decision(state: OverallState) -> dict[str, Any]:
    comparison = state.get("measurement_comparison_result") or {}
    validation = state.get("submission_validation_result") or {}
    visual = state.get("vl_analysis_result") or {}
    if validation.get("status") == "need_resubmission":
        final_result = "need_resubmission"
        grade = "incomplete"
    elif int(comparison.get("critical_fail_count") or 0) > 0:
        final_result = "fail"
        grade = "needs_review"
    elif int(comparison.get("dimension_fail_count") or 0) > 0:
        final_result = "fail"
        grade = "needs_review"
    elif visual.get("overall_visual_status") in {"severe", "fail"}:
        final_result = "needs_manual_review"
        grade = "manual_review"
    elif visual.get("overall_visual_status") == "warning":
        final_result = "pass_with_warning"
        grade = "passed"
    else:
        final_result = "pass"
        grade = "passed"
    return {
        "final_result": final_result,
        "grade": grade,
        "score": _score_for(final_result, comparison),
        "decision_source": "measurement_primary_rule",
    }


def _score_for(final_result: str, comparison: dict[str, Any]) -> int:
    if final_result == "need_resubmission":
        return 0
    total = (
        int(comparison.get("dimension_pass_count") or 0)
        + int(comparison.get("dimension_fail_count") or 0)
        + int(comparison.get("dimension_missing_count") or 0)
    )
    if total <= 0:
        return 0
    score = round(100 * int(comparison.get("dimension_pass_count") or 0) / total)
    if final_result == "needs_manual_review":
        return min(score, 79)
    return score


def _invoke_review_llm(state: OverallState, decision: dict[str, Any]) -> dict[str, Any]:
    try:
        response = _review_model_from_state(state).invoke([_human_message(_review_prompt(state, decision))])
    except ModuleNotFoundError:
        return _fallback_report(decision)
    data = _load_json_object(str(getattr(response, "content", response)))
    return data or _fallback_report(decision)


def _review_model_from_state(state: OverallState) -> Any:
    return state.get("_review_model") or state.get("_feedback_model") or state.get("_model") or _default_review_model()


def _default_review_model() -> Any:
    global _review_model
    if _review_model is None:
        from langchain_deepseek import ChatDeepSeek

        _review_model = ChatDeepSeek(
            model=RagConfig.from_env().deepseek_model,
            extra_body={"thinking": {"type": "disabled"}},
        )
    return _review_model


def _review_prompt(state: OverallState, decision: dict[str, Any]) -> str:
    return f"""
You are a CNC machining review assistant. The final pass/fail decision is already made by deterministic
measurement rules. Do not change it. Return JSON only with summary, student_feedback, and recommendations.

rule_based_decision:
{json.dumps(decision, ensure_ascii=False)}

measurement_comparison_result:
{json.dumps(state.get("measurement_comparison_result") or {}, ensure_ascii=False)}

vl_analysis_result:
{json.dumps(state.get("vl_analysis_result") or {}, ensure_ascii=False)}
""".strip()


def _fallback_report(decision: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": f"Operation review result: {decision.get('final_result')}",
        "student_feedback": "Review the dimension comparison and visual warnings before the next attempt.",
        "recommendations": ["Check measurement records and machining setup."],
    }


def _profile_update_suggestions(state: OverallState, result: dict[str, Any]) -> dict[str, Any]:
    comparison = state.get("measurement_comparison_result") or {}
    visual = state.get("vl_analysis_result") or {}
    validation = state.get("submission_validation_result") or {}
    failed = [
        item
        for item in comparison.get("dimension_results", [])
        if isinstance(item, dict) and item.get("result") in {"fail", "missing"}
    ]
    knowledge_gap_patches = _operation_knowledge_gap_patches(state, result, failed)
    return {
        "feedback_assessment": {
            "feedback_type": "practice_feedback",
            "confidence": 0.96 if result.get("final_result") in {"pass", "pass_with_warning"} else 0.92,
            "rationale": "deterministic operation review from measurement comparison and visual inspection",
        },
        "capability_evidence": _operation_capability_evidence(state, result, visual, validation, comparison),
        "knowledge_gap_patches": knowledge_gap_patches,
        "operation_gap_patches": knowledge_gap_patches,
        "progress_patches": [
            {
                "course_id": str(state.get("course_id") or ""),
                "chapter_id": str(state.get("chapter_id") or ""),
                "status": "completed" if result.get("final_result") in {"pass", "pass_with_warning"} else "needs_review",
                "completion_rate": 1.0 if result.get("final_result") in {"pass", "pass_with_warning"} else 0.7,
            }
        ],
        "markdown_patch": {
            "section": "上机操作反馈",
            "content": _profile_markdown_summary(state, result, comparison, visual),
        },
    }


def _operation_capability_evidence(
    state: OverallState,
    result: dict[str, Any],
    visual: dict[str, Any],
    validation: dict[str, Any],
    comparison: dict[str, Any],
) -> list[dict[str, Any]]:
    attempt_id = str(state.get("submission_id") or state.get("request_id") or result.get("decision_source") or "operation")
    chapter_id = str(state.get("chapter_id") or "")
    task_id = str(state.get("task_id") or "")
    score_ratio = min(max(float(result.get("score") or 0) / 100.0, 0.0), 1.0)
    pass_like = result.get("final_result") in {"pass", "pass_with_warning"}
    warning_like = result.get("final_result") == "pass_with_warning" or visual.get("overall_visual_status") == "warning"
    severe_like = result.get("final_result") in {"fail", "needs_manual_review"} or visual.get("overall_visual_status") in {"severe", "fail"}

    items = [
        _capability_evidence_item(
            attempt_id=attempt_id,
            chapter_id=chapter_id,
            task_id=task_id,
            dimension="quality_control",
            topic="尺寸与公差控制",
            knowledge_point="上机尺寸检测与公差判定",
            earned=score_ratio,
            possible=1.0,
            correct=pass_like,
            severity="high" if severe_like else "medium",
            review_status="auto_verified",
            reason=f"measurement result score={result.get('score')} final_result={result.get('final_result')}",
        ),
        _capability_evidence_item(
            attempt_id=attempt_id,
            chapter_id=chapter_id,
            task_id=task_id,
            dimension="machining_operation",
            topic="工件操作与外观检查",
            knowledge_point="上机操作流程与工件状态检查",
            earned=0.85 if pass_like and not warning_like else 0.45 if warning_like else 0.15,
            possible=1.0,
            correct=pass_like and not warning_like,
            severity="medium" if warning_like or severe_like else "low",
            review_status="auto_verified",
            reason=f"visual status={visual.get('overall_visual_status') or 'unknown'}",
        ),
    ]
    if validation.get("status") == "need_resubmission":
        items.append(
            _capability_evidence_item(
                attempt_id=attempt_id,
                chapter_id=chapter_id,
                task_id=task_id,
                dimension="safety",
                topic="提交完整性与上机安全",
                knowledge_point="上机提交完整性检查",
                earned=0.0,
                possible=1.0,
                correct=False,
                severity="high",
                review_status="reviewed",
                reason="submission validation requires resubmission",
            )
        )
    else:
        items.append(
            _capability_evidence_item(
                attempt_id=attempt_id,
                chapter_id=chapter_id,
                task_id=task_id,
                dimension="safety",
                topic="安全检查与操作规范",
                knowledge_point="上机安全流程与规范执行",
                earned=0.9 if pass_like else 0.35,
                possible=1.0,
                correct=pass_like,
                severity="medium" if severe_like else "low",
                review_status="auto_verified",
                reason="submission passed validation" if pass_like else "operation result needs review",
            )
        )
    if any(item.get("result") in {"fail", "missing"} for item in comparison.get("dimension_results", [])):
        items.append(
            _capability_evidence_item(
                attempt_id=attempt_id,
                chapter_id=chapter_id,
                task_id=task_id,
                dimension="process_planning",
                topic="加工顺序与工艺安排",
                knowledge_point="上机工艺安排与顺序控制",
                earned=0.8 if pass_like else 0.25,
                possible=1.0,
                correct=pass_like,
                severity="medium" if severe_like else "low",
                review_status="auto_verified",
                reason="measurement comparison shows failed or missing dimensions",
            )
        )
    return [item for item in items if item]


def _capability_evidence_item(
    *,
    attempt_id: str,
    chapter_id: str,
    task_id: str,
    dimension: str,
    topic: str,
    knowledge_point: str,
    earned: float,
    possible: float,
    correct: bool,
    severity: str,
    review_status: str,
    reason: str,
) -> dict[str, Any]:
    if dimension not in CAPABILITY_DIMENSION_IDS:
        return {}
    return {
        "id": f"{attempt_id}-{dimension}-{_slug(knowledge_point)}",
        "attemptId": attempt_id,
        "sourceType": "practice",
        "dimension": dimension,
        "topic": topic,
        "knowledgePoint": knowledge_point,
        "correct": correct,
        "earned": max(0.0, min(float(earned), float(possible))),
        "possible": max(float(possible), 0.0001),
        "difficulty": "medium",
        "knowledgePointId": f"{chapter_id or 'operation'}.{_slug(knowledge_point)}",
        "dimensionSource": "declared",
        "questionGrounded": True,
        "reviewStatus": review_status,
        "chapterId": chapter_id,
        "taskId": task_id,
        "criticalSafetyError": dimension == "safety" and severity == "high" and not correct,
        "sourceRefs": [f"operation_review::{dimension}"],
        "ragChunkIds": [],
        "gradingMethod": "deterministic_operation_review",
        "rubricVersion": "operation_review_v1",
        "coreExamPoints": [topic, knowledge_point],
        "evidenceReason": reason,
    }


def _operation_knowledge_gap_patches(
    state: OverallState,
    result: dict[str, Any],
    failed: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    chapter_id = str(state.get("chapter_id") or "")
    task_id = str(state.get("task_id") or "")
    final_result = str(result.get("final_result") or "")
    patches = []
    for item in failed:
        name = str(item.get("display_name") or item.get("name") or "").strip()
        if not name:
            continue
        severity = "high" if item.get("importance") == "critical" else "medium"
        patches.append(
            {
                "gap_id": f"operation-{_slug(task_id or 'task')}-{_slug(name)}",
                "knowledge_point_id": f"operation.{_slug(name)}",
                "concept": name,
                "chapter_id": chapter_id,
                "category": "quality_control",
                "severity": severity,
                "score": 0.0 if final_result in {"fail", "needs_manual_review", "need_resubmission"} else 0.3,
                "evidence": (
                    f"{item.get('name')} result={item.get('result')} "
                    f"actual={item.get('actual')} target={item.get('target')}"
                ),
                "evidence_items": [
                    {
                        "dimension": item.get("name"),
                        "display_name": item.get("display_name"),
                        "actual": item.get("actual"),
                        "target": item.get("target"),
                        "result": item.get("result"),
                        "importance": item.get("importance"),
                    }
                ],
                "recommended_actions": [
                    "复核标准尺寸与测量记录",
                    "重新检查加工参数与刀路设置",
                ],
                "status": "open",
                "source": "operation_review",
            }
        )
    return patches


def _profile_markdown_summary(
    state: OverallState,
    result: dict[str, Any],
    comparison: dict[str, Any],
    visual: dict[str, Any],
) -> str:
    chapter_id = str(state.get("chapter_id") or "")
    task_id = str(state.get("task_id") or "")
    lines = [
        f"- 章节: {chapter_id}",
        f"- 任务: {task_id}",
        f"- 最终结果: {result.get('final_result')}",
        f"- 得分: {result.get('score')}",
        f"- 视觉状态: {visual.get('overall_visual_status') or 'unknown'}",
        f"- 尺寸通过数: {comparison.get('dimension_pass_count') or 0}",
        f"- 尺寸失败数: {comparison.get('dimension_fail_count') or 0}",
        f"- 缺失数: {comparison.get('dimension_missing_count') or 0}",
    ]
    return "\n".join(lines)


def _slug(value: str) -> str:
    token = re.sub(r"[^0-9A-Za-z_.-]+", "_", str(value).strip()).strip("_")
    return token or "item"


def _persist_json_if_path(state: OverallState, key: str, payload: dict[str, Any]) -> None:
    paths = state.get("operation_review_paths")
    if isinstance(paths, dict) and paths.get(key):
        write_operation_review_json(
            relative_path=str(paths[key]),
            payload=payload,
            storage_root=state.get("_storage_root"),
        )


def _persist_report_if_path(state: OverallState, content: str) -> None:
    paths = state.get("operation_review_paths")
    if isinstance(paths, dict) and paths.get("llm_review_report"):
        write_operation_review_markdown(
            relative_path=str(paths["llm_review_report"]),
            content=content,
            storage_root=state.get("_storage_root"),
        )


def _markdown_report(result: dict[str, Any]) -> str:
    report = result.get("llm_report") if isinstance(result.get("llm_report"), dict) else {}
    lines = [
        "# Operation Review Report",
        "",
        f"- Final result: {result.get('final_result')}",
        f"- Score: {result.get('score')}",
        "",
        "## Summary",
        "",
        str(report.get("summary") or ""),
        "",
        "## Feedback",
        "",
        str(report.get("student_feedback") or ""),
        "",
        "## Recommendations",
        "",
    ]
    for item in report.get("recommendations") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def _load_json_object(text: str) -> dict[str, Any]:
    cleaned = str(text).strip()
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


def _vl_message_content(prompt: str, uploaded_images: list[dict[str, Any]]) -> list[dict[str, str]]:
    content = [{"text": prompt}]
    for image in uploaded_images:
        path = str(image.get("path") or image.get("url") or "").strip()
        if not path:
            continue
        if re.match(r"^https?://", path) or path.startswith("file://"):
            image_ref = path
        else:
            image_ref = f"file://{Path(path).resolve().as_posix()}"
        content.append({"image": image_ref})
    return content


def _human_message(content: Any) -> Any:
    try:
        from langchain.messages import HumanMessage
    except ModuleNotFoundError:
        from langchain_core.messages import HumanMessage
    return HumanMessage(content)


def _default_submission_id() -> str:
    from uuid import uuid4

    return f"submission_{uuid4().hex[:12]}"
