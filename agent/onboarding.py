from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from agent.tools.profile.manager import ProfileManager


ONBOARDING_QUESTIONS: list[dict[str, Any]] = [
    {
        "id": "onboarding_background_001",
        "stem": "你之前有没有接触过数控车床或类似的加工设备？",
        "question_type": "single_choice",
        "options": ["几乎没有接触过", "听过或见过，但没实际操作过", "有过简单接触", "比较熟悉"],
        "answer": "D",
        "capability_dimension": "background",
        "knowledge_points": [
            {"id": "cnc_lathe.background.experience", "name": "数控学习与实训经历", "weight": 1.0}
        ],
        "difficulty": "easy",
        "points": 1,
    },
    {
        "id": "onboarding_background_002",
        "stem": "你对零件图和尺寸标注的熟悉程度更接近哪一种？",
        "question_type": "single_choice",
        "options": ["基本看不懂", "能看懂一点简单标注", "大部分常见标注能理解", "能比较熟练地阅读"],
        "answer": "C",
        "capability_dimension": "background",
        "knowledge_points": [
            {"id": "cnc_lathe.background.drawing_reading", "name": "图纸阅读基础", "weight": 1.0}
        ],
        "difficulty": "easy",
        "points": 1,
    },
    {
        "id": "onboarding_background_003",
        "stem": "你之前是否做过上机实训、仿真训练或类似操作练习？",
        "question_type": "single_choice",
        "options": ["完全没有", "只做过很少量体验", "做过一段时间", "做过较系统的训练"],
        "answer": "D",
        "capability_dimension": "background",
        "knowledge_points": [
            {"id": "cnc_lathe.background.practice_experience", "name": "上机与仿真经验", "weight": 1.0}
        ],
        "difficulty": "easy",
        "points": 1,
    },
    {
        "id": "onboarding_background_004",
        "stem": "你对加工中的安全要求、急停、报警这些内容的了解程度如何？",
        "question_type": "single_choice",
        "options": ["几乎不了解", "知道一些基本概念", "比较清楚常见要求", "比较熟悉并能独立判断"],
        "answer": "C",
        "capability_dimension": "background",
        "knowledge_points": [
            {"id": "cnc_lathe.background.safety_awareness", "name": "安全意识基础", "weight": 1.0}
        ],
        "difficulty": "easy",
        "points": 1,
    },
    {
        "id": "onboarding_knowledge_001",
        "stem": "数控加工中，程序的作用更接近下面哪项？",
        "question_type": "single_choice",
        "options": ["告诉机床按什么步骤和轨迹加工", "只是记录操作员姓名", "只用于显示时间", "只用于给刀具编号"],
        "answer": "A",
        "capability_dimension": "foundations",
        "knowledge_points": [
            {"id": "cnc_lathe.1.2.program_role", "name": "程序与加工控制", "weight": 1.0}
        ],
        "difficulty": "easy",
        "points": 1,
    },
    {
        "id": "onboarding_knowledge_002",
        "stem": "开机后如果要先稳妥地确认程序是否有问题，通常应该怎么做？",
        "question_type": "single_choice",
        "options": ["直接全速加工", "先空运行或做仿真检查", "先把进给调到最大", "直接跳过首件"],
        "answer": "B",
        "capability_dimension": "machining_operation",
        "knowledge_points": [
            {"id": "cnc_lathe.operation.dry_run", "name": "空运行与仿真检查", "weight": 1.0}
        ],
        "difficulty": "medium",
        "points": 1,
    },
    {
        "id": "onboarding_knowledge_003",
        "stem": "判断加工结果是否合格时，应该主要看什么？",
        "question_type": "single_choice",
        "options": ["加工时间", "图样尺寸和公差", "机床颜色", "操作者经验"],
        "answer": "B",
        "capability_dimension": "quality_control",
        "knowledge_points": [
            {"id": "cnc_lathe.quality.dimension_tolerance", "name": "尺寸与公差判定", "weight": 1.0}
        ],
        "difficulty": "medium",
        "points": 1,
    },
    {
        "id": "onboarding_knowledge_004",
        "stem": "遇到机床报警或异常时，最合适的第一步是什么？",
        "question_type": "single_choice",
        "options": ["继续运行看看", "立即停止并按规定处理", "直接关闭所有提示不管", "提高转速再试一次"],
        "answer": "B",
        "capability_dimension": "safety",
        "knowledge_points": [
            {"id": "cnc_lathe.safety.abnormal_stop", "name": "异常报警与停机处理", "weight": 1.0}
        ],
        "difficulty": "easy",
        "points": 1,
    },
    {
        "id": "onboarding_knowledge_005",
        "stem": "G00 在数控编程里通常表示什么？",
        "question_type": "single_choice",
        "options": ["快速定位", "直线插补", "程序结束", "主轴停止"],
        "answer": "A",
        "capability_dimension": "programming",
        "knowledge_points": [
            {"id": "cnc_lathe.4.1.rapid_positioning", "name": "快速定位指令", "weight": 1.0}
        ],
        "difficulty": "easy",
        "points": 1,
    },
    {
        "id": "onboarding_knowledge_006",
        "stem": "G01 在数控编程里通常表示什么？",
        "question_type": "single_choice",
        "options": ["快速定位", "直线插补", "圆弧插补", "程序结束"],
        "answer": "B",
        "capability_dimension": "programming",
        "knowledge_points": [
            {"id": "cnc_lathe.4.1.linear_interpolation", "name": "直线插补", "weight": 1.0}
        ],
        "difficulty": "easy",
        "points": 1,
    },
    {
        "id": "onboarding_safety_001",
        "stem": "开机前你最先应该确认哪一项？",
        "question_type": "single_choice",
        "options": ["直接启动主轴", "急停、护罩和润滑状态", "先把转速调到最高", "先跳过空运行"],
        "answer": "B",
        "capability_dimension": "safety",
        "knowledge_points": [
            {"id": "cnc_lathe.onboarding.safety.precheck", "name": "开机前检查", "weight": 1.0}
        ],
        "difficulty": "easy",
        "points": 1,
    },
    {
        "id": "onboarding_safety_002",
        "stem": "听到报警或发现异常振动时，第一步应该怎么做？",
        "question_type": "single_choice",
        "options": ["继续加工并观察", "立即停机并按规程处理", "先加快进给再看", "直接关闭显示屏"],
        "answer": "B",
        "capability_dimension": "safety",
        "knowledge_points": [
            {"id": "cnc_lathe.onboarding.safety.abnormal_stop", "name": "异常停机处理", "weight": 1.0}
        ],
        "difficulty": "easy",
        "points": 1,
    },
    {
        "id": "onboarding_foundations_001",
        "stem": "G00 通常表示什么？",
        "question_type": "single_choice",
        "options": ["直线插补", "快速定位", "程序结束", "主轴停止"],
        "answer": "B",
        "capability_dimension": "foundations",
        "knowledge_points": [
            {"id": "cnc_lathe.onboarding.foundations.g00", "name": "快速定位指令", "weight": 1.0}
        ],
        "difficulty": "easy",
        "points": 1,
    },
    {
        "id": "onboarding_foundations_002",
        "stem": "G01 通常表示什么？",
        "question_type": "single_choice",
        "options": ["快速定位", "直线插补", "圆弧插补", "程序结束"],
        "answer": "B",
        "capability_dimension": "foundations",
        "knowledge_points": [
            {"id": "cnc_lathe.onboarding.foundations.g01", "name": "直线插补", "weight": 1.0}
        ],
        "difficulty": "easy",
        "points": 1,
    },
    {
        "id": "onboarding_process_planning_001",
        "stem": "开始编写加工路线前，你通常最先要考虑什么？",
        "question_type": "single_choice",
        "options": ["先看机床颜色", "先估算加工时间", "先看图纸尺寸、公差和加工顺序", "先直接下刀"],
        "answer": "C",
        "capability_dimension": "process_planning",
        "knowledge_points": [
            {"id": "cnc_lathe.onboarding.process_planning.route", "name": "工艺路线规划", "weight": 1.0}
        ],
        "difficulty": "medium",
        "points": 1,
    },
    {
        "id": "onboarding_process_planning_002",
        "stem": "选择刀具和工艺参数时，下面哪项最关键？",
        "question_type": "single_choice",
        "options": ["只看加工时间", "只看机床新旧", "只看操作员熟练度", "看材料、余量、精度和装夹方式"],
        "answer": "D",
        "capability_dimension": "process_planning",
        "knowledge_points": [
            {"id": "cnc_lathe.onboarding.process_planning.parameters", "name": "装夹与余量判断", "weight": 1.0}
        ],
        "difficulty": "medium",
        "points": 1,
    },
    {
        "id": "onboarding_programming_001",
        "stem": "G90 一般表示什么？",
        "question_type": "single_choice",
        "options": ["圆弧插补", "绝对编程", "子程序结束", "快速退刀"],
        "answer": "B",
        "capability_dimension": "programming",
        "knowledge_points": [
            {"id": "cnc_lathe.onboarding.programming.g90", "name": "绝对编程", "weight": 1.0}
        ],
        "difficulty": "easy",
        "points": 1,
    },
    {
        "id": "onboarding_programming_002",
        "stem": "G91 一般表示什么？",
        "question_type": "single_choice",
        "options": ["主轴正转", "绝对编程", "增量编程", "取消刀补"],
        "answer": "C",
        "capability_dimension": "programming",
        "knowledge_points": [
            {"id": "cnc_lathe.onboarding.programming.g91", "name": "增量编程", "weight": 1.0}
        ],
        "difficulty": "easy",
        "points": 1,
    },
    {
        "id": "onboarding_machining_operation_001",
        "stem": "试运行程序时，最合适的做法是什么？",
        "question_type": "single_choice",
        "options": ["直接全速切削", "空运行或单段检查", "跳过首件", "先把进给调到最大"],
        "answer": "B",
        "capability_dimension": "machining_operation",
        "knowledge_points": [
            {"id": "cnc_lathe.onboarding.operation.dry_run", "name": "空运行与单段检查", "weight": 1.0}
        ],
        "difficulty": "easy",
        "points": 1,
    },
    {
        "id": "onboarding_machining_operation_002",
        "stem": "对刀的主要目的更接近哪一项？",
        "question_type": "single_choice",
        "options": ["记录时间", "增大切削深度", "建立刀具与工件坐标关系", "提高主轴噪音"],
        "answer": "C",
        "capability_dimension": "machining_operation",
        "knowledge_points": [
            {"id": "cnc_lathe.onboarding.operation.tool_setting", "name": "对刀与坐标建立", "weight": 1.0}
        ],
        "difficulty": "medium",
        "points": 1,
    },
    {
        "id": "onboarding_quality_control_001",
        "stem": "判断尺寸是否合格时，最核心看什么？",
        "question_type": "single_choice",
        "options": ["加工时间", "主轴噪音", "尺寸公差和图纸要求", "操作者经验"],
        "answer": "C",
        "capability_dimension": "quality_control",
        "knowledge_points": [
            {"id": "cnc_lathe.onboarding.quality_control.tolerance", "name": "尺寸公差判定", "weight": 1.0}
        ],
        "difficulty": "easy",
        "points": 1,
    },
    {
        "id": "onboarding_quality_control_002",
        "stem": "测量前先做什么更稳妥？",
        "question_type": "single_choice",
        "options": ["直接测一次就行", "先把读数四舍五入", "先确认量具零位和清洁", "先加大夹紧力"],
        "answer": "C",
        "capability_dimension": "quality_control",
        "knowledge_points": [
            {"id": "cnc_lathe.onboarding.quality_control.gauge", "name": "量具零位检查", "weight": 1.0}
        ],
        "difficulty": "easy",
        "points": 1,
    },
    {
        "id": "onboarding_maintenance_001",
        "stem": "日常维护里最基本的一步是什么？",
        "question_type": "single_choice",
        "options": ["清洁、润滑并检查异常", "频繁重启", "把报警全关掉", "只要开机就行"],
        "answer": "A",
        "capability_dimension": "maintenance",
        "knowledge_points": [
            {"id": "cnc_lathe.onboarding.maintenance.routine", "name": "日常维护与润滑", "weight": 1.0}
        ],
        "difficulty": "easy",
        "points": 1,
    },
    {
        "id": "onboarding_maintenance_002",
        "stem": "设备出现异响时，最合适的处理是？",
        "question_type": "single_choice",
        "options": ["继续运行", "提高进给", "停机检查并报修", "把声音调小"],
        "answer": "C",
        "capability_dimension": "maintenance",
        "knowledge_points": [
            {"id": "cnc_lathe.onboarding.maintenance.noise", "name": "异常声音与报修", "weight": 1.0}
        ],
        "difficulty": "easy",
        "points": 1,
    },
    {
        "id": "onboarding_advanced_manufacturing_001",
        "stem": "你是否接触过多轴、复合加工、CAM 或仿真这类内容？",
        "question_type": "single_choice",
        "options": ["完全没接触", "听过但没做过", "做过一点", "比较熟悉"],
        "answer": "D",
        "capability_dimension": "advanced_manufacturing",
        "knowledge_points": [
            {"id": "cnc_lathe.onboarding.advanced_manufacturing.exposure", "name": "多轴与CAM基础", "weight": 1.0}
        ],
        "difficulty": "medium",
        "points": 1,
    },
    {
        "id": "onboarding_advanced_manufacturing_002",
        "stem": "在智能制造相关内容里，你对远程监控、数据采集和工艺联动的熟悉度更接近哪一项？",
        "question_type": "single_choice",
        "options": ["基本不了解", "只听过名词", "能理解常见概念", "能结合场景做简单分析"],
        "answer": "D",
        "capability_dimension": "advanced_manufacturing",
        "knowledge_points": [
            {"id": "cnc_lathe.onboarding.advanced_manufacturing.smart", "name": "智能制造与数据联动", "weight": 1.0}
        ],
        "difficulty": "medium",
        "points": 1,
    },
]

ONBOARDING_OPTION_SCORES: dict[str, dict[str, float]] = {
    "onboarding_background_001": {"A": 0.0, "B": 0.33, "C": 0.67, "D": 1.0},
    "onboarding_background_002": {"A": 0.0, "B": 0.33, "C": 1.0, "D": 0.67},
    "onboarding_background_003": {"A": 0.0, "B": 0.33, "C": 0.67, "D": 1.0},
    "onboarding_background_004": {"A": 0.0, "B": 0.33, "C": 1.0, "D": 0.67},
    "onboarding_knowledge_001": {"A": 1.0, "B": 0.33, "C": 0.0, "D": 0.0},
    "onboarding_knowledge_002": {"A": 0.0, "B": 1.0, "C": 0.33, "D": 0.0},
    "onboarding_knowledge_003": {"A": 0.0, "B": 1.0, "C": 0.33, "D": 0.0},
    "onboarding_knowledge_004": {"A": 0.0, "B": 1.0, "C": 0.33, "D": 0.0},
    "onboarding_knowledge_005": {"A": 1.0, "B": 0.33, "C": 0.0, "D": 0.0},
    "onboarding_knowledge_006": {"A": 0.0, "B": 1.0, "C": 0.33, "D": 0.0},
    "onboarding_safety_001": {"A": 0.0, "B": 1.0, "C": 0.33, "D": 0.0},
    "onboarding_safety_002": {"A": 0.0, "B": 1.0, "C": 0.33, "D": 0.0},
    "onboarding_foundations_001": {"A": 0.33, "B": 1.0, "C": 0.0, "D": 0.0},
    "onboarding_foundations_002": {"A": 0.0, "B": 1.0, "C": 0.33, "D": 0.0},
    "onboarding_process_planning_001": {"A": 0.0, "B": 0.33, "C": 1.0, "D": 0.0},
    "onboarding_process_planning_002": {"A": 0.0, "B": 0.0, "C": 0.33, "D": 1.0},
    "onboarding_programming_001": {"A": 0.0, "B": 1.0, "C": 0.33, "D": 0.0},
    "onboarding_programming_002": {"A": 0.0, "B": 0.33, "C": 1.0, "D": 0.0},
    "onboarding_machining_operation_001": {"A": 0.0, "B": 1.0, "C": 0.33, "D": 0.0},
    "onboarding_machining_operation_002": {"A": 0.0, "B": 0.0, "C": 1.0, "D": 0.0},
    "onboarding_quality_control_001": {"A": 0.0, "B": 0.0, "C": 1.0, "D": 0.33},
    "onboarding_quality_control_002": {"A": 0.0, "B": 0.0, "C": 1.0, "D": 0.0},
    "onboarding_maintenance_001": {"A": 1.0, "B": 0.33, "C": 0.0, "D": 0.0},
    "onboarding_maintenance_002": {"A": 0.0, "B": 0.33, "C": 1.0, "D": 0.0},
    "onboarding_advanced_manufacturing_001": {"A": 0.0, "B": 0.33, "C": 0.67, "D": 1.0},
    "onboarding_advanced_manufacturing_002": {"A": 0.0, "B": 0.33, "C": 0.67, "D": 1.0},
}

ONBOARDING_LEVEL_THRESHOLDS = {
    "beginner": 40,
    "standard": 80,
}

ONBOARDING_RADAR_DIMENSIONS = {
    "safety",
    "foundations",
    "process_planning",
    "programming",
    "machining_operation",
    "quality_control",
    "maintenance",
    "advanced_manufacturing",
}

_ASSESSMENT_SESSIONS: dict[str, dict[str, Any]] = {}


def create_onboarding_assessment(
    *,
    course_id: str = "cnc_lathe",
    assessment_id: str | None = None,
) -> dict[str, Any]:
    session_id = assessment_id or f"assessment_{uuid4().hex[:12]}"
    session = {
        "assessment_id": session_id,
        "course_id": course_id,
        "status": "created",
        "created_at": _now(),
        "scoring_policy": _scoring_policy(),
        "questions": _client_questions(ONBOARDING_QUESTIONS),
    }
    _ASSESSMENT_SESSIONS[session_id] = session
    return deepcopy(session)


def submit_onboarding_assessment(
    *,
    assessment_id: str,
    answers: list[dict[str, Any]],
) -> dict[str, Any]:
    session = _ASSESSMENT_SESSIONS.get(assessment_id)
    if session is None:
        raise KeyError("assessment not found")
    result = score_onboarding_answers(
        assessment_id=assessment_id,
        course_id=str(session.get("course_id") or "cnc_lathe"),
        answers=answers,
    )
    session["status"] = "submitted"
    session["submitted_at"] = _now()
    session["result"] = result
    return deepcopy(result)


def score_onboarding_answers(
    *,
    assessment_id: str,
    course_id: str,
    answers: list[dict[str, Any]],
) -> dict[str, Any]:
    answers_by_id = {
        str(item.get("question_id") or item.get("id") or "").strip(): str(item.get("answer") or "").strip().upper()
        for item in answers
        if isinstance(item, dict)
    }
    scored_items = [_score_question(question, answers_by_id.get(question["id"], "")) for question in ONBOARDING_QUESTIONS]
    radar_items = _radar_scored_items(scored_items)
    total_possible = sum(float(item["possible"]) for item in radar_items) or 1.0
    total_earned = sum(float(item["earned"]) for item in radar_items)
    overall_score = round(100 * total_earned / total_possible)
    dimension_scores = _dimension_scores(scored_items)
    learner_level = _learner_level(overall_score)
    metrics = _metrics_from_dimension_scores(dimension_scores)
    scoring_policy = _scoring_policy()
    capability_evidence = [_capability_evidence(course_id, assessment_id, item) for item in radar_items]
    knowledge_gap_patches = [_gap_patch(course_id, item) for item in radar_items if not item["correct"]]
    path_assignment = {
        "course_id": course_id,
        "learner_level": learner_level,
        "path_id": learner_level,
        "path_version": "",
        "classification_source": "onboarding_assessment",
        "classification_score": overall_score,
        "classification_reason": f"入门测评总分 {overall_score}，按规则分配到 {learner_level} 路径。",
        "manual_override": False,
    }
    suggestions = {
        "source_node": "onboarding_assessment",
        "feedback_assessment": {
            "feedback_type": "external_assessment",
            "confidence": 1.0,
            "rationale": "deterministic onboarding question bank scoring",
        },
        "metric_patches": [
            {"field": field, "value": value, "reason": "onboarding_assessment"}
            for field, value in metrics.items()
        ],
        "capability_evidence": capability_evidence,
        "knowledge_gap_patches": knowledge_gap_patches,
        "progress_patches": [
            {
                "course_id": course_id,
                "path_id": learner_level,
                "chapter_id": "1.1",
                "chapter_order": 1,
                "status": "in_progress",
                "completion_rate": 0.0,
            }
        ],
        "markdown_patch": {
            "section": "初始化测评结果",
            "content": _assessment_markdown(overall_score, learner_level, scoring_policy, metrics, knowledge_gap_patches),
        },
    }
    return {
        "assessment_id": assessment_id,
        "course_id": course_id,
        "status": "scored",
        "overall_score": overall_score,
        "learner_level": learner_level,
        "scoring_policy": scoring_policy,
        "dimension_scores": dimension_scores,
        "metrics": metrics,
        "scored_items": scored_items,
        "capability_evidence": capability_evidence,
        "knowledge_gap_patches": knowledge_gap_patches,
        "path_assignment": path_assignment,
        "profile_update_suggestions": suggestions,
    }


def register_onboarding_user(
    *,
    user_id: str,
    assessment_result: dict[str, Any],
    display_name: str | None = None,
    background_type: str | None = None,
    storage_root: str | Path | None = None,
) -> dict[str, Any]:
    user_id = str(user_id or "").strip()
    if not user_id:
        raise ValueError("user_id is required")
    if not isinstance(assessment_result, dict) or assessment_result.get("status") != "scored":
        raise ValueError("assessment_result must be a scored onboarding result")

    manager = ProfileManager(storage_root)
    profile_context = manager.load_profile_context(
        user_id,
        display_name=display_name,
        background_type=background_type,
    )
    path_assignment = manager.assign_learning_path(user_id, assessment_result["path_assignment"])
    profile_update = manager.apply_update_suggestions(
        user_id,
        str(assessment_result.get("assessment_id") or ""),
        assessment_result.get("profile_update_suggestions") or {},
    )
    return {
        "status": "registered",
        "user_id": user_id,
        "assessment_result": assessment_result,
        "path_assignment": path_assignment,
        "profile_update_result": profile_update,
        "profile_context": manager.load_profile_context(user_id),
        "initial_profile_context": profile_context,
    }


def registered_users(*, storage_root: str | Path | None = None) -> list[dict[str, Any]]:
    return ProfileManager(storage_root).list_users()


def assessment_result_for(assessment_id: str) -> dict[str, Any] | None:
    session = _ASSESSMENT_SESSIONS.get(assessment_id)
    result = session.get("result") if isinstance(session, dict) else None
    return deepcopy(result) if isinstance(result, dict) else None


def _client_questions(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {key: deepcopy(value) for key, value in question.items() if key != "answer"}
        for question in questions
    ]


def _score_question(question: dict[str, Any], answer: str) -> dict[str, Any]:
    correct_answer = str(question.get("answer") or "").strip().upper()
    option_scores = _option_scores_for(question)
    selected_score = float(option_scores.get(answer, 0.0))
    max_score = max(option_scores.values()) if option_scores else 1.0
    correct = bool(answer) and answer == correct_answer
    return {
        "question_id": question["id"],
        "selected_answer": answer,
        "correct_answer": correct_answer,
        "correct": correct,
        "selected_score": selected_score,
        "max_score": max_score,
        "earned": float(question.get("points") or 1) * selected_score,
        "possible": float(question.get("points") or 1),
        "dimension": str(question.get("capability_dimension") or "foundations"),
        "difficulty": str(question.get("difficulty") or "easy"),
        "knowledge_points": deepcopy(question.get("knowledge_points") or []),
        "stem": str(question.get("stem") or ""),
        "option_scores": deepcopy(option_scores),
    }


def _option_scores_for(question: dict[str, Any]) -> dict[str, float]:
    question_id = str(question.get("id") or "").strip()
    scores = ONBOARDING_OPTION_SCORES.get(question_id)
    if isinstance(scores, dict) and scores:
        return {str(key).strip().upper(): float(value) for key, value in scores.items()}
    answer = str(question.get("answer") or "").strip().upper()
    return {answer: 1.0} if answer else {}


def _dimension_scores(scored_items: list[dict[str, Any]]) -> dict[str, float]:
    dimensions = {}
    for item in scored_items:
        dimension = str(item["dimension"])
        bucket = dimensions.setdefault(dimension, {"earned": 0.0, "possible": 0.0})
        bucket["earned"] += float(item["earned"])
        bucket["possible"] += float(item["possible"])
    return {
        dimension: round(100 * bucket["earned"] / bucket["possible"])
        for dimension, bucket in dimensions.items()
        if bucket["possible"]
    }


def _radar_scored_items(scored_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in scored_items if str(item.get("dimension") or "") in ONBOARDING_RADAR_DIMENSIONS]


def _metrics_from_dimension_scores(dimension_scores: dict[str, float]) -> dict[str, float]:
    operation_values = [
        dimension_scores.get("machining_operation", 0.0),
        dimension_scores.get("quality_control", 0.0),
    ]
    return {
        "theory_score": float(dimension_scores.get("foundations", 0.0)),
        "safety_score": float(dimension_scores.get("safety", 0.0)),
        "operation_score": float(round(sum(operation_values) / len(operation_values))),
        "programming_score": float(dimension_scores.get("programming", 0.0)),
    }


def _learner_level(overall_score: int) -> str:
    if overall_score >= ONBOARDING_LEVEL_THRESHOLDS["standard"]:
        return "advanced"
    if overall_score >= ONBOARDING_LEVEL_THRESHOLDS["beginner"]:
        return "standard"
    return "beginner"


def _capability_evidence(course_id: str, assessment_id: str, item: dict[str, Any]) -> dict[str, Any]:
    point = _primary_knowledge_point(item)
    chapter_id = _chapter_for_knowledge_point(point["id"], item["dimension"])
    return {
        "id": f"{assessment_id}-{item['question_id']}",
        "attemptId": assessment_id,
        "sourceType": "external_assessment",
        "dimension": item["dimension"],
        "topic": f"{course_id}:onboarding",
        "knowledgePoint": point["name"],
        "knowledgePointId": point["id"],
        "correct": bool(item["correct"]),
        "earned": float(item["earned"]),
        "possible": float(item["possible"]),
        "difficulty": item["difficulty"],
        "occurredAt": _now(),
        "sourceRefs": [],
        "ragChunkIds": [],
        "questionType": "single_choice",
        "attemptNumber": 1,
        "itemRevision": item["question_id"],
        "dimensionSource": "declared",
        "questionGrounded": True,
        "reviewStatus": "reviewed",
        "reviewedBy": "onboarding_deterministic_grader",
        "chapterId": chapter_id,
        "objectiveIds": [f"{chapter_id}:{item['dimension']}"],
        "coreExamPoints": [point["name"]],
    }


def _gap_patch(course_id: str, item: dict[str, Any]) -> dict[str, Any]:
    point = _primary_knowledge_point(item)
    chapter_id = _chapter_for_knowledge_point(point["id"], item["dimension"])
    return {
        "gap_id": f"gap_onboarding_{course_id}_{point['id'].replace('.', '_')}",
        "knowledge_point_id": point["id"],
        "concept": point["name"],
        "chapter_id": chapter_id,
        "category": item["dimension"],
        "severity": "high" if item["difficulty"] == "easy" else "medium",
        "score": 0.0,
        "evidence": f"入门测评题目 {item['question_id']} 作答错误。",
        "evidence_items": [
            {
                "assessment_item_id": item["question_id"],
                "knowledge_point_id": point["id"],
                "correct": False,
                "earned": float(item["earned"]),
                "possible": float(item["possible"]),
                "source": "onboarding_assessment",
            }
        ],
        "status": "open",
        "source": "onboarding_assessment",
        "recommended_actions": [f"优先复习“{point['name']}”相关基础内容。"],
    }


def _chapter_for_knowledge_point(point_id: str, dimension: str) -> str:
    match = re.search(r"(?:^|\.)([1-5]\.\d+)(?:\.|$)", str(point_id or ""))
    if match:
        return match.group(1)
    return {
        "foundations": "1.1",
        "safety": "2.1",
        "machining_operation": "3.1",
        "programming": "4.1",
        "process_planning": "4.2",
        "quality_control": "5.1",
        "maintenance": "5.2",
        "advanced_manufacturing": "5.3",
    }.get(str(dimension or ""), "1.1")


def _primary_knowledge_point(item: dict[str, Any]) -> dict[str, str]:
    points = item.get("knowledge_points")
    if isinstance(points, list) and points:
        first = points[0] if isinstance(points[0], dict) else {}
        point_id = str(first.get("id") or first.get("name") or item["question_id"])
        name = str(first.get("name") or point_id)
        return {"id": point_id, "name": name}
    return {"id": str(item["question_id"]), "name": str(item["stem"])}


def _assessment_markdown(
    overall_score: int,
    learner_level: str,
    scoring_policy: dict[str, Any],
    metrics: dict[str, float],
    gaps: list[dict[str, Any]],
) -> str:
    lines = [
        f"- 入门测评总分: {overall_score}",
        f"- 初始学习路径: {learner_level}",
        f"- 分值规则: A={scoring_policy['option_scores']['A']}, B={scoring_policy['option_scores']['B']}, C={scoring_policy['option_scores']['C']}, D={scoring_policy['option_scores']['D']}",
        f"- 路径分界: beginner<{ONBOARDING_LEVEL_THRESHOLDS['beginner']} < standard<{ONBOARDING_LEVEL_THRESHOLDS['standard']} <= advanced",
        f"- 理论基础: {metrics['theory_score']}",
        f"- 安全规范: {metrics['safety_score']}",
        f"- 操作与质量: {metrics['operation_score']}",
        f"- 数控编程: {metrics['programming_score']}",
    ]
    if gaps:
        lines.append("- 初始薄弱点: " + "、".join(str(gap["concept"]) for gap in gaps[:5]))
    else:
        lines.append("- 初始薄弱点: 暂无明显薄弱项。")
    return "\n".join(lines)


def _scoring_policy() -> dict[str, Any]:
    return {
        "mode": "graded_option_scoring",
        "option_scores": {
            "A": 0.0,
            "B": 0.33,
            "C": 0.67,
            "D": 1.0,
        },
        "level_thresholds": {
            "beginner": ONBOARDING_LEVEL_THRESHOLDS["beginner"],
            "standard": ONBOARDING_LEVEL_THRESHOLDS["standard"],
            "advanced": 100,
        },
        "path_mapping": {
            "beginner": "beginner",
            "standard": "standard",
            "advanced": "advanced",
        },
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
