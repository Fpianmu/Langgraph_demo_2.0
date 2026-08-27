from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from agent.state import OverallState
from agent.tools.cnc_simulation_tools import (
    create_cnc_simulation_submission,
    load_cnc_exercise,
    load_cnc_simulation_rules,
    save_cnc_simulation_artifact,
)
from agent.tools.cncjs_simulation_api import CncjsSimulationApiClient, CncjsSimulationApiError


load_dotenv(override=True)


def cnc_exercise_loader_node(state: OverallState) -> OverallState:
    course_id = str(state.get("course_id") or "cnc_lathe")
    chapter_id = str(state.get("chapter_id") or "4.1")
    task_id = str(state.get("task_id") or "task_001")
    exercise = load_cnc_exercise(course_id, chapter_id, task_id, resource_root=state.get("_course_resource_root"))
    rules = load_cnc_simulation_rules(course_id, resource_root=state.get("_course_resource_root"))
    return {
        "cnc_feedback_intent": "submit_simulation_review",
        "task_id": task_id,
        "cnc_task_bundle": exercise,
        "cnc_simulation_rules": rules,
    }


def cnc_submission_loader_node(state: OverallState) -> OverallState:
    source_code = str(state.get("source_code") or state.get("hnc_code") or "").strip()
    if not source_code:
        raise ValueError("chapter4 CNC feedback requires source_code or hnc_code")
    submission = create_cnc_simulation_submission(
        user_id=str(state.get("user_id") or "default_user"),
        course_id=str(state.get("course_id") or "cnc_lathe"),
        chapter_id=str(state.get("chapter_id") or "4.1"),
        task_id=str(state.get("task_id") or "task_001"),
        source_code=source_code if source_code.endswith("\n") else source_code + "\n",
        submission_id=state.get("submission_id"),
        request_id=str(state.get("request_id") or ""),
        resource_root=state.get("_course_resource_root"),
        storage_root=state.get("_storage_root"),
    )
    paths = {
        "submission": submission["submission"],
        "source_code": submission["source_code"],
    }
    return {
        "submission_id": submission["submission_id"],
        "hnc_code": source_code,
        "cnc_feedback_paths": paths,
        "cnc_submission_load_result": {
            "status": "created",
            "submission_id": submission["submission_id"],
            "source_code_path": submission["source_code"],
        },
    }


def cnc_input_normalizer_node(state: OverallState) -> OverallState:
    normalized = _normalize_code(str(state.get("hnc_code") or ""))
    saved = _save_text_artifact(state, "normalized_code.nc", normalized)
    return {
        "normalized_code": normalized,
        "cnc_feedback_paths": _paths_with(state, "normalized_code", saved["path"]),
    }


def hnc_semantic_conversion_node(state: OverallState) -> OverallState:
    normalized = str(state.get("normalized_code") or "")
    rule_context = _semantic_rule_context(state)
    lines = [line for line in normalized.splitlines() if line.strip()]
    converted = []
    line_mapping = []
    warnings = []
    unsupported = []
    for index, line in enumerate(lines, start=1):
        converted_line = _normalize_modal_codes(line)
        converted.append(converted_line)
        line_mapping.append({"hnc_line": index, "gcode_line": len(converted), "source": line, "target": converted_line})
        for token in re.findall(r"\bG\d+\b|\bM\d+\b", converted_line):
            if token not in _SUPPORTED_SIMULATION_CODES:
                severity = "blocking" if token.startswith("G") else "warning"
                item = {"line_number": index, "code": token, "line": line, "severity": severity}
                if severity == "blocking":
                    unsupported.append(item)
                else:
                    warnings.append(item)
    standard_gcode = "\n".join(converted).rstrip() + "\n"
    result = {
        "status": "converted_with_risk" if unsupported or warnings else "success",
        "standard_gcode": standard_gcode,
        "line_mapping": line_mapping,
        "conversion_warnings": warnings,
        "unsupported_instructions": unsupported,
        "rule_context": rule_context,
    }
    saved = _save_json_artifact(state, "semantic_program.json", result)
    return {
        "standard_gcode": standard_gcode,
        "hnc_semantic_conversion_result": result,
        "cnc_feedback_paths": _paths_with(state, "semantic_program", saved["path"]),
    }


def cncjs_preview_node(state: OverallState) -> OverallState:
    conversion = state.get("hnc_semantic_conversion_result") or {}
    diagnostics = []
    for item in conversion.get("unsupported_instructions") or []:
        instruction = item.get("code")
        diagnostic = {key: value for key, value in item.items() if key != "code"}
        diagnostic["instruction"] = instruction
        diagnostics.append(
            {
                "severity": "blocking",
                "source": "semantic_converter",
                "code": "UNSUPPORTED_INSTRUCTION",
                **diagnostic,
            }
        )
    gcode = str(state.get("standard_gcode") or "")
    positions = _extract_positions(gcode)
    cncjs_job = {}
    preview_engine = "offline-placeholder"
    if not diagnostics:
        try:
            cncjs_job = _cncjs_client(state).create_and_fetch_job(
                gcode=gcode,
                name=f"{state.get('submission_id') or 'student'}.nc",
                metadata={
                    "course_id": str(state.get("course_id") or ""),
                    "chapter_id": str(state.get("chapter_id") or ""),
                    "task_id": str(state.get("task_id") or ""),
                    "submission_id": str(state.get("submission_id") or ""),
                },
            )
            preview_engine = "cncjs-simulation-api"
        except CncjsSimulationApiError as exc:
            diagnostics.append(
                {
                    "severity": "warning",
                    "source": "cncjs_simulation_api",
                    "code": "CNCJS_API_UNAVAILABLE",
                    "message": str(exc),
                    "status": exc.status,
                    "payload": exc.payload,
                }
            )
    result = {
        "status": "failed" if any(item.get("severity") == "blocking" for item in diagnostics) else "loaded",
        "line_count": len([line for line in gcode.splitlines() if line.strip()]),
        "diagnostics": diagnostics,
        "toolpath_bounds": _bounds(positions),
        "preview_engine": preview_engine,
        "cncjs_job": _cncjs_job_summary(cncjs_job),
    }
    saved = _save_json_artifact(state, "cncjs_preview_result.json", result)
    return {
        "cncjs_preview_result": result,
        "cnc_feedback_paths": _paths_with(state, "cncjs_preview_result", saved["path"]),
    }


def hnc_raw_code_check_node(state: OverallState) -> OverallState:
    code = str(state.get("normalized_code") or state.get("hnc_code") or "")
    diagnostics = []
    executable = [line for line in code.splitlines() if line.strip() and not line.strip().startswith("(")]
    if not executable:
        diagnostics.append({"severity": "error", "code": "EMPTY_PROGRAM", "message": "程序内容为空"})
    if not any(re.search(r"\bM(?:02|2|30)\b", line) for line in executable):
        diagnostics.append({"severity": "error", "code": "MISSING_PROGRAM_END", "message": "缺少 M2/M30 程序结束"})
    if "G41" in code or "G42" in code:
        diagnostics.append({"severity": "warning", "code": "TOOL_COMP_UNSUPPORTED", "message": "第一版暂不展开刀尖补偿"})
    result = {
        "status": "pass" if not any(item["severity"] == "error" for item in diagnostics) else "fail",
        "diagnostics": diagnostics,
    }
    saved = _save_json_artifact(state, "raw_code_check_result.json", result)
    return {
        "hnc_raw_check_result": result,
        "cnc_feedback_paths": _paths_with(state, "raw_code_check_result", saved["path"]),
    }


def cnc_expected_result_check_node(state: OverallState) -> OverallState:
    expected = _read_json_asset((state.get("cnc_task_bundle") or {}).get("expected_result"))
    standard_dimensions = _read_json_asset((state.get("cnc_task_bundle") or {}).get("standard_dimensions"))
    code = str(state.get("normalized_code") or state.get("hnc_code") or "")
    preview = state.get("cncjs_preview_result") or {}
    raw = state.get("hnc_raw_check_result") or {}
    diagnostics = []
    check_results = []

    for end_code in _required_end_codes(expected):
        if not _contains_modal_code(code, end_code):
            diagnostics.append(
                {
                    "severity": "error",
                    "source": "expected_result",
                    "code": "MISSING_REQUIRED_PROGRAM_END",
                    "message": f"预期结果要求使用 {end_code} 结束程序",
                    "expected": end_code,
                }
            )

    if _has_diagnostic_code(preview.get("diagnostics"), "CNCJS_API_UNAVAILABLE"):
        diagnostics.append(
            {
                "severity": "manual_review",
                "source": "cncjs_simulation_api",
                "code": "SIMULATION_UNAVAILABLE",
                "message": "仿真服务不可用，本次结果需要人工复核后再确认是否合格。",
            }
        )

    for check_id in _required_checks(expected):
        check_results.append(_evaluate_required_check(check_id, state, expected, standard_dimensions))

    diagnostics.extend(
        item["diagnostic"]
        for item in check_results
        if isinstance(item.get("diagnostic"), dict)
    )
    status = "pass"
    if any(item.get("severity") in {"blocking", "error"} for item in diagnostics):
        status = "fail"
    elif any(item.get("severity") == "manual_review" for item in diagnostics):
        status = "needs_manual_review"
    result = {
        "status": status,
        "pass_policy": str(expected.get("pass_policy") or "all_required_checks_pass"),
        "required_checks": _required_checks(expected),
        "check_results": check_results,
        "diagnostics": diagnostics,
    }
    saved = _save_json_artifact(state, "expected_result_check.json", result)
    return {
        "cnc_expected_result_check": result,
        "cnc_feedback_paths": _paths_with(state, "expected_result_check", saved["path"]),
    }


def cnc_result_merger_node(state: OverallState) -> OverallState:
    preview = state.get("cncjs_preview_result") or {}
    raw = state.get("hnc_raw_check_result") or {}
    expected = state.get("cnc_expected_result_check") or {}
    diagnostics = []
    diagnostics.extend(preview.get("diagnostics") or [])
    diagnostics.extend(raw.get("diagnostics") or [])
    diagnostics.extend(expected.get("diagnostics") or [])
    final_result = "pass"
    if any(item.get("severity") in {"blocking", "error"} for item in diagnostics):
        final_result = "fail"
    elif expected.get("status") == "needs_manual_review" or any(item.get("severity") == "manual_review" for item in diagnostics):
        final_result = "needs_manual_review"
    result = {
        "status": "reviewed",
        "final_result": final_result,
        "diagnostics": diagnostics,
        "cncjs_status": preview.get("status"),
        "raw_check_status": raw.get("status"),
        "expected_result_check_status": expected.get("status"),
        "expected_result_check": expected,
        "toolpath_bounds": preview.get("toolpath_bounds") or {},
    }
    saved = _save_json_artifact(state, "merged_result.json", result)
    return {
        "cnc_merged_review_result": result,
        "cnc_feedback_paths": _paths_with(state, "merged_result", saved["path"]),
    }


def cnc_answer_snapshot_node(state: OverallState) -> OverallState:
    task = state.get("cnc_task_bundle") or {}
    snapshot = {
        "reference_code": _read_text_asset(task.get("reference_code")),
        "standard_dimensions": _read_json_asset(task.get("standard_dimensions")),
        "expected_result": _read_json_asset(task.get("expected_result")),
        "task_manifest_path": task.get("task_manifest_path"),
    }
    saved = _save_json_artifact(state, "answer_snapshot.json", snapshot)
    return {
        "cnc_answer_snapshot": snapshot,
        "cnc_feedback_paths": _paths_with(state, "answer_snapshot", saved["path"]),
    }


def cnc_diagnosis_node(state: OverallState) -> OverallState:
    raw = _invoke_diagnosis_model(state)
    diagnosis = _load_json_object(raw) or _fallback_diagnosis(state)
    saved_json = _save_json_artifact(state, "diagnosis.json", diagnosis)
    feedback = _feedback_markdown(diagnosis)
    saved_md = _save_text_artifact(state, "feedback.md", feedback)
    paths = _paths_with(state, "diagnosis", saved_json["path"])
    paths["feedback"] = saved_md["path"]
    return {
        "cnc_diagnosis_result": diagnosis,
        "cnc_feedback_paths": paths,
    }


def cnc_feedback_profile_update_node(state: OverallState) -> OverallState:
    diagnostics = (state.get("cnc_merged_review_result") or {}).get("diagnostics") or []
    merged = state.get("cnc_merged_review_result") or {}
    final_result = str(merged.get("final_result") or "unknown")
    suggestions = _cnc_profile_suggestions(state, final_result, diagnostics)
    packet = _cnc_profile_evidence_packet(state, suggestions, final_result)
    saved = _save_json_artifact(state, "profile_evidence_packet.json", packet)
    paths = _paths_with(state, "profile_evidence_packet", saved["path"])
    return {
        "cnc_profile_update_suggestions": suggestions,
        "profile_update_suggestions": suggestions,
        "profile_evidence_packet": packet,
        "cnc_feedback_paths": paths,
        "feedback_assessment": suggestions["feedback_assessment"],
        "cnc_profile_update_result": {
            "accepted": False,
            "source": "chapter4_cnc_simulation_feedback",
            "review_status": "pending_profile_assessment_review" if _has_cnc_profile_changes(suggestions) else "no_valid_profile_changes",
            "suggestions": suggestions,
        },
    }


def _required_end_codes(expected: dict[str, Any]) -> list[str]:
    value = expected.get("required_end_codes")
    if isinstance(value, list):
        codes = [str(item).strip().upper() for item in value if str(item).strip()]
    else:
        codes = []
    single = str(expected.get("required_program_end") or "").strip().upper()
    if single:
        codes.append(single)
    return codes or ["M30"]


def _contains_modal_code(code: str, modal_code: str) -> bool:
    normalized = _normalize_modal_codes(str(modal_code).strip().upper())
    match = re.match(r"^([GM])(\d+)$", normalized)
    if not match:
        return normalized in code.upper()
    letter, number = match.groups()
    return bool(re.search(rf"\b{letter}0*{int(number)}\b", code.upper()))


def _required_checks(expected: dict[str, Any]) -> list[str]:
    value = expected.get("required_checks")
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _evaluate_required_check(
    check_id: str,
    state: OverallState,
    expected: dict[str, Any],
    standard_dimensions: dict[str, Any],
) -> dict[str, Any]:
    if check_id == "program_syntax":
        passed = (state.get("hnc_raw_check_result") or {}).get("status") == "pass"
        return _check_result(check_id, passed, "原码检查通过", "原码检查存在 error 级问题")
    if check_id == "coordinate_and_tool_setup":
        code = str(state.get("normalized_code") or "")
        passed = bool(re.search(r"\b[GXZ]-?\d", code)) and bool(re.search(r"\bF\d", code))
        return _check_result(check_id, passed, "程序包含坐标运动和进给参数", "程序缺少必要坐标运动或进给参数")
    if check_id == "safe_toolpath":
        diagnostics = (state.get("cncjs_preview_result") or {}).get("diagnostics") or []
        passed = not any(item.get("severity") == "blocking" for item in diagnostics if isinstance(item, dict))
        return _check_result(check_id, passed, "未发现 blocking 级刀路风险", "存在 blocking 级刀路或语义风险")
    if check_id == "standard_dimensions":
        bounds = (state.get("cncjs_preview_result") or {}).get("toolpath_bounds") or {}
        passed = _has_toolpath_bounds(bounds) and bool(standard_dimensions.get("dimensions") or expected.get("expected_geometry"))
        return _check_result(check_id, passed, "刀路边界和标准尺寸资料均可用于复核", "缺少刀路边界或标准尺寸资料")
    return {
        "check_id": check_id,
        "status": "pending_review",
        "diagnostic": {
            "severity": "manual_review",
            "source": "expected_result",
            "code": "UNKNOWN_REQUIRED_CHECK",
            "message": f"未知预期检查项 {check_id}，需要人工复核。",
            "check_id": check_id,
        },
    }


def _check_result(check_id: str, passed: bool, pass_message: str, fail_message: str) -> dict[str, Any]:
    result = {"check_id": check_id, "status": "pass" if passed else "fail"}
    if not passed:
        result["diagnostic"] = {
            "severity": "error",
            "source": "expected_result",
            "code": f"REQUIRED_CHECK_FAILED_{check_id.upper()}",
            "message": fail_message,
            "check_id": check_id,
        }
    else:
        result["message"] = pass_message
    return result


def _has_toolpath_bounds(bounds: dict[str, Any]) -> bool:
    return any(bounds.get(key) is not None for key in ("min_x", "max_x", "min_z", "max_z"))


def _has_diagnostic_code(value: Any, code: str) -> bool:
    return any(isinstance(item, dict) and item.get("code") == code for item in (value or []))


def _cnc_profile_suggestions(state: OverallState, final_result: str, diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
    capability_evidence = _cnc_capability_evidence(state, final_result, diagnostics)
    knowledge_gaps = _cnc_knowledge_gap_patches(state, diagnostics)
    progress_status = "completed" if final_result == "pass" else "needs_review"
    completion_rate = 1.0 if final_result == "pass" else 0.7
    return {
        "source": "chapter4_cnc_simulation_feedback",
        "feedback_assessment": {
            "feedback_type": "practice_feedback",
            "confidence": 0.95 if final_result == "pass" else 0.85,
            "rationale": "structured CNC simulation, raw code checks, expected-result checks, and diagnosis artifacts",
        },
        "capability_evidence": capability_evidence,
        "knowledge_gap_patches": knowledge_gaps,
        "progress_patches": [
            {
                "course_id": str(state.get("course_id") or ""),
                "chapter_id": str(state.get("chapter_id") or ""),
                "status": progress_status,
                "completion_rate": completion_rate,
            }
        ],
    }


def _cnc_capability_evidence(state: OverallState, final_result: str, diagnostics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    attempt_id = str(state.get("submission_id") or state.get("request_id") or "cnc_submission")
    occurred_at = _now()
    if final_result == "pass":
        return [
            _capability_item(
                state,
                evidence_id=f"{attempt_id}-cnc-simulation-pass",
                dimension="programming",
                knowledge_point="CNC 程序仿真综合通过",
                knowledge_point_id="cnc_lathe.4.1.cnc_simulation_pass",
                correct=True,
                earned=1.0,
                possible=1.0,
                occurred_at=occurred_at,
                review_status="auto_verified",
                core_exam_points=["程序结构完整性", "仿真结果通过", "程序结束指令"],
            )
        ]

    evidence = []
    for index, diagnostic in enumerate(diagnostics, start=1):
        if not isinstance(diagnostic, dict) or diagnostic.get("code") == "CNCJS_API_UNAVAILABLE":
            continue
        mapping = _diagnostic_capability_mapping(diagnostic)
        if diagnostic.get("severity") == "manual_review":
            review_status = "pending_review"
            earned = 0.0
        else:
            review_status = "auto_verified"
            earned = 0.0 if diagnostic.get("severity") in {"blocking", "error"} else 0.5
        evidence.append(
            _capability_item(
                state,
                evidence_id=f"{attempt_id}-cnc-diagnostic-{index}-{_safe_id(str(diagnostic.get('code') or 'diagnostic'))}",
                dimension=mapping["dimension"],
                knowledge_point=mapping["knowledge_point"],
                knowledge_point_id=mapping["knowledge_point_id"],
                correct=False,
                earned=earned,
                possible=1.0,
                occurred_at=occurred_at,
                review_status=review_status,
                core_exam_points=mapping["core_exam_points"],
                grading_result={"diagnostic": diagnostic, "final_result": final_result},
            )
        )
    return evidence


def _capability_item(
    state: OverallState,
    *,
    evidence_id: str,
    dimension: str,
    knowledge_point: str,
    knowledge_point_id: str,
    correct: bool,
    earned: float,
    possible: float,
    occurred_at: str,
    review_status: str,
    core_exam_points: list[str],
    grading_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": evidence_id,
        "attemptId": str(state.get("submission_id") or state.get("request_id") or evidence_id),
        "sourceType": "practice",
        "dimension": dimension,
        "topic": f"{state.get('course_id') or ''}:{state.get('chapter_id') or ''}",
        "knowledgePoint": knowledge_point,
        "knowledgePointId": knowledge_point_id,
        "correct": correct,
        "earned": earned,
        "possible": possible,
        "difficulty": "medium",
        "occurredAt": occurred_at,
        "sourceRefs": _string_list_from_paths(state.get("cnc_feedback_paths") or {}),
        "questionType": "cnc_simulation",
        "gradingMethod": "cnc_rule_and_simulation_check",
        "rubricVersion": "cnc-simulation-v1",
        "graderConfidence": 0.95 if review_status == "auto_verified" else 0.5,
        "gradingResult": grading_result or {"final_result": (state.get("cnc_merged_review_result") or {}).get("final_result")},
        "coreExamPoints": core_exam_points,
        "attemptNumber": 1,
        "itemRevision": str(state.get("task_id") or "task_001"),
        "dimensionSource": "declared",
        "questionGrounded": True,
        "reviewStatus": review_status,
        "chapterId": str(state.get("chapter_id") or ""),
        "objectiveIds": ["cnc_simulation_programming"],
        "criticalSafetyError": dimension == "safety" and not correct,
    }


def _diagnostic_capability_mapping(diagnostic: dict[str, Any]) -> dict[str, Any]:
    code = str(diagnostic.get("code") or "")
    if code in {"MISSING_PROGRAM_END", "MISSING_REQUIRED_PROGRAM_END"}:
        return {
            "dimension": "programming",
            "knowledge_point": "程序结束指令",
            "knowledge_point_id": "cnc_lathe.4.1.program_end",
            "core_exam_points": ["M30 程序结束", "程序结构完整性"],
        }
    if code in {"UNSUPPORTED_INSTRUCTION", "TOOL_COMP_UNSUPPORTED"}:
        return {
            "dimension": "programming",
            "knowledge_point": "华中数控指令适配",
            "knowledge_point_id": "cnc_lathe.4.1.hnc_instruction_mapping",
            "core_exam_points": ["HNC 指令识别", "仿真前程序检查"],
        }
    if code == "SIMULATION_UNAVAILABLE":
        return {
            "dimension": "programming",
            "knowledge_point": "仿真结果人工复核",
            "knowledge_point_id": "cnc_lathe.4.1.simulation_review",
            "core_exam_points": ["仿真结果复核", "证据完整性"],
        }
    if code.startswith("REQUIRED_CHECK_FAILED_SAFE_TOOLPATH"):
        return {
            "dimension": "safety",
            "knowledge_point": "安全刀路检查",
            "knowledge_point_id": "cnc_lathe.4.1.safe_toolpath",
            "core_exam_points": ["安全退刀", "刀具路径检查"],
        }
    if code.startswith("REQUIRED_CHECK_FAILED_STANDARD_DIMENSIONS"):
        return {
            "dimension": "quality_control",
            "knowledge_point": "标准尺寸复核",
            "knowledge_point_id": "cnc_lathe.4.1.standard_dimensions",
            "core_exam_points": ["标准尺寸", "加工结果判定"],
        }
    return {
        "dimension": "programming",
        "knowledge_point": code or "CNC 程序检查",
        "knowledge_point_id": f"cnc_lathe.4.1.{_safe_id(code or 'program_check')}",
        "core_exam_points": ["CNC 程序检查"],
    }


def _cnc_knowledge_gap_patches(state: OverallState, diagnostics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    patches = []
    for diagnostic in diagnostics:
        if not isinstance(diagnostic, dict):
            continue
        if diagnostic.get("severity") == "manual_review" or diagnostic.get("code") == "CNCJS_API_UNAVAILABLE":
            continue
        mapping = _diagnostic_capability_mapping(diagnostic)
        evidence = str(diagnostic.get("message") or diagnostic.get("line") or diagnostic.get("code") or "").strip()
        if not evidence:
            continue
        patches.append(
            {
                "gap_id": _gap_id_for_cnc(state, mapping["knowledge_point_id"]),
                "knowledge_point_id": mapping["knowledge_point_id"],
                "concept": mapping["knowledge_point"],
                "chapter_id": str(state.get("chapter_id") or ""),
                "category": mapping["dimension"],
                "severity": "high" if diagnostic.get("severity") in {"blocking", "error"} else "medium",
                "score": 0.25 if diagnostic.get("severity") in {"blocking", "error"} else 0.55,
                "evidence": evidence,
                "evidence_items": [diagnostic],
                "recommended_actions": _recommended_actions_for_diagnostic(diagnostic),
                "status": "open",
                "source": "cnc_simulation",
            }
        )
    return patches


def _recommended_actions_for_diagnostic(diagnostic: dict[str, Any]) -> list[str]:
    code = str(diagnostic.get("code") or "")
    if code in {"MISSING_PROGRAM_END", "MISSING_REQUIRED_PROGRAM_END"}:
        return ["补充 M30 程序结束段后重新仿真。"]
    if code == "UNSUPPORTED_INSTRUCTION":
        return ["对照华中数控指令表确认该指令是否可被当前仿真器支持。"]
    if code == "TOOL_COMP_UNSUPPORTED":
        return ["暂时避免使用 G41/G42，或改用当前仿真任务支持的刀路表达。"]
    return ["根据 CNC 仿真反馈修改程序后重新提交。"]


def _cnc_profile_evidence_packet(state: OverallState, suggestions: dict[str, Any], final_result: str) -> dict[str, Any]:
    packet_id = str(state.get("request_id") or state.get("submission_id") or f"cnc-{state.get('task_id') or 'task'}")
    return {
        "packet_id": packet_id,
        "packet_type": "profile_evidence_packet",
        "source_type": "cnc_simulation",
        "source_node": "cnc_feedback_profile_update_node",
        "user_id": str(state.get("user_id") or "default_user"),
        "course_id": str(state.get("course_id") or ""),
        "chapter_id": str(state.get("chapter_id") or ""),
        "task_id": str(state.get("task_id") or ""),
        "attempt_id": str(state.get("submission_id") or packet_id),
        "overall_result": final_result,
        "confidence": 0.95 if final_result == "pass" else 0.85,
        "student_visible_feedback": str((state.get("cnc_diagnosis_result") or {}).get("student_feedback") or ""),
        "proposed_profile_changes": suggestions,
        "artifact_refs": state.get("cnc_feedback_paths") or {},
    }


def _has_cnc_profile_changes(suggestions: dict[str, Any]) -> bool:
    return bool(
        suggestions.get("capability_evidence")
        or suggestions.get("knowledge_gap_patches")
        or suggestions.get("progress_patches")
    )


def _gap_id_for_cnc(state: OverallState, knowledge_point_id: str) -> str:
    return "gap_" + "_".join(
        _safe_id(str(part))
        for part in (
            state.get("user_id") or "default_user",
            state.get("course_id") or "cnc_lathe",
            state.get("chapter_id") or "",
            knowledge_point_id,
        )
        if str(part).strip()
    )


def _string_list_from_paths(paths: dict[str, Any]) -> list[str]:
    return [str(value) for value in paths.values() if str(value).strip()]


def _safe_id(value: str) -> str:
    token = re.sub(r"[^0-9A-Za-z_.-]+", "_", str(value).strip()).strip("_")
    return token or "item"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_code(code: str) -> str:
    lines = []
    for line in code.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = re.sub(r"\s+", " ", line.strip().upper())
        if stripped:
            lines.append(stripped)
    return "\n".join(lines).rstrip() + "\n"


def _normalize_modal_codes(line: str) -> str:
    def replace(match: re.Match[str]) -> str:
        letter = match.group(1)
        number = int(match.group(2))
        return f"{letter}{number}"

    return re.sub(r"\b([GM])0*(\d+)\b", replace, line)


def _extract_positions(gcode: str) -> list[dict[str, float]]:
    positions = []
    current = {"x": 0.0, "z": 0.0}
    for line in gcode.splitlines():
        next_pos = dict(current)
        for axis in ("X", "Z"):
            match = re.search(rf"\b{axis}(-?\d+(?:\.\d+)?)", line)
            if match:
                next_pos[axis.lower()] = float(match.group(1))
        if next_pos != current:
            positions.append(next_pos)
            current = next_pos
    return positions


def _bounds(positions: list[dict[str, float]]) -> dict[str, float] | dict[str, None]:
    if not positions:
        return {"min_x": None, "max_x": None, "min_z": None, "max_z": None}
    xs = [item["x"] for item in positions]
    zs = [item["z"] for item in positions]
    return {"min_x": min(xs), "max_x": max(xs), "min_z": min(zs), "max_z": max(zs)}


def _semantic_rule_context(state: OverallState) -> dict[str, dict[str, Any]]:
    rules = state.get("cnc_simulation_rules") or {}
    context = {}
    for key in ("hnc_gcode_mapping", "hnc_instruction_table", "hnc_programming_rules"):
        asset = rules.get(key)
        if not isinstance(asset, dict):
            continue
        path = Path(str(asset.get("path") or ""))
        exists = path.exists()
        content = ""
        if exists:
            content = path.read_text(encoding="utf-8")[:8000]
        context[key] = {
            "path": str(path),
            "exists": exists,
            "content": content,
            "truncated": exists and path.stat().st_size > len(content.encode("utf-8")),
        }
    return context


def _cncjs_client(state: OverallState) -> Any:
    injected = state.get("_cncjs_client")
    if injected is not None:
        return injected
    return CncjsSimulationApiClient()


def _cncjs_job_summary(result: dict[str, Any]) -> dict[str, Any]:
    created = result.get("created") if isinstance(result, dict) and isinstance(result.get("created"), dict) else {}
    fetched = result.get("fetched") if isinstance(result, dict) and isinstance(result.get("fetched"), dict) else {}
    job = fetched.get("job") if isinstance(fetched, dict) else {}
    if not created and not fetched and not job:
        return {}
    return {
        "job_id": created.get("job_id") or job.get("id"),
        "status": fetched.get("status") or created.get("status"),
        "expires_at": fetched.get("expires_at"),
        "api_version": fetched.get("api_version") or created.get("api_version"),
        "job": job,
    }


def _invoke_diagnosis_model(state: OverallState) -> str:
    model = state.get("_diagnosis_model")
    if model is None:
        model = _default_diagnosis_model()
    if model is None:
        return json.dumps(_fallback_diagnosis(state), ensure_ascii=False)
    prompt = _diagnosis_prompt(state)
    response = model.invoke([_human_message(prompt)])
    return str(getattr(response, "content", response))


def _default_diagnosis_model() -> Any:
    if not os.getenv("DEEPSEEK_API_KEY"):
        return None
    try:
        from langchain_deepseek import ChatDeepSeek
    except ModuleNotFoundError:
        return None
    return ChatDeepSeek(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        extra_body={"thinking": {"type": "disabled"}},
    )


def _diagnosis_prompt(state: OverallState) -> str:
    payload = {
        "original_hnc_code": state.get("hnc_code") or "",
        "standard_gcode": state.get("standard_gcode") or "",
        "semantic_conversion": state.get("hnc_semantic_conversion_result") or {},
        "merged_result": state.get("cnc_merged_review_result") or {},
        "answer_snapshot": state.get("cnc_answer_snapshot") or {},
    }
    return (
        "你是华中数控代码仿真反馈节点。请只返回 JSON，字段包含 "
        "summary, student_feedback, recommendations。输入如下：\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def _fallback_diagnosis(state: OverallState) -> dict[str, Any]:
    result = state.get("cnc_merged_review_result") or {}
    final_result = result.get("final_result") or "unknown"
    return {
        "summary": f"CNC simulation review result: {final_result}",
        "student_feedback": "请根据结构化诊断检查程序结束、进给、刀具路径和不支持指令。",
        "recommendations": ["优先修复 blocking/error 级别诊断，再重新仿真。"],
    }


def _feedback_markdown(diagnosis: dict[str, Any]) -> str:
    lines = ["# CNC 仿真反馈", "", f"## 总结", "", str(diagnosis.get("summary") or ""), "", "## 给学生的反馈", "", str(diagnosis.get("student_feedback") or ""), "", "## 修改建议", ""]
    for item in _recommendation_items(diagnosis.get("recommendations")):
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def _recommendation_items(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _load_json_object(text: str) -> dict[str, Any]:
    cleaned = str(text).strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if not match:
            return {}
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
    return data if isinstance(data, dict) else {}


def _human_message(content: str) -> Any:
    try:
        from langchain.messages import HumanMessage
    except ModuleNotFoundError:
        from langchain_core.messages import HumanMessage
    return HumanMessage(content)


def _read_text_asset(asset: Any) -> str:
    if not isinstance(asset, dict) or not asset.get("path"):
        return ""
    path = Path(str(asset["path"]))
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _read_json_asset(asset: Any) -> dict[str, Any]:
    if not isinstance(asset, dict) or not asset.get("path"):
        return {}
    path = Path(str(asset["path"]))
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _save_json_artifact(state: OverallState, artifact_name: str, content: Any) -> dict[str, str]:
    return save_cnc_simulation_artifact(
        user_id=str(state.get("user_id") or "default_user"),
        course_id=str(state.get("course_id") or "cnc_lathe"),
        chapter_id=str(state.get("chapter_id") or "4.1"),
        task_id=str(state.get("task_id") or "task_001"),
        attempt_id=str(state.get("submission_id") or ""),
        artifact_name=artifact_name,
        content=content,
        storage_root=state.get("_storage_root"),
    )


def _save_text_artifact(state: OverallState, artifact_name: str, content: str) -> dict[str, str]:
    return save_cnc_simulation_artifact(
        user_id=str(state.get("user_id") or "default_user"),
        course_id=str(state.get("course_id") or "cnc_lathe"),
        chapter_id=str(state.get("chapter_id") or "4.1"),
        task_id=str(state.get("task_id") or "task_001"),
        attempt_id=str(state.get("submission_id") or ""),
        artifact_name=artifact_name,
        content=content,
        storage_root=state.get("_storage_root"),
    )


def _paths_with(state: OverallState, key: str, path: str) -> dict[str, str]:
    paths = dict(state.get("cnc_feedback_paths") or {})
    paths[key] = path
    return paths


_SUPPORTED_SIMULATION_CODES = {
    "G0",
    "G1",
    "G2",
    "G3",
    "G18",
    "G20",
    "G21",
    "G90",
    "G91",
    "G94",
    "G95",
    "G97",
    "M0",
    "M1",
    "M2",
    "M3",
    "M4",
    "M5",
    "M7",
    "M8",
    "M9",
    "M30",
}
