from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AgentInfo:
    agent_id: str
    display_name: str
    folder: str
    activity_text: str


AGENT_REGISTRY: dict[str, AgentInfo] = {
    "task_dispatch": AgentInfo("task_dispatch", "任务调度 Agent", "task_dispatch", "正在理解任务"),
    "knowledge_generation": AgentInfo(
        "knowledge_generation",
        "知识检索与生成 Agent",
        "knowledge_generation",
        "正在检索与生成材料",
    ),
    "learning_management": AgentInfo("learning_management", "学情管理 Agent", "learning_management", "正在处理学情"),
    "personalized_generation": AgentInfo(
        "personalized_generation",
        "个性化生成 Agent",
        "personalized_generation",
        "正在个性化生成",
    ),
    "hallucination_elimination": AgentInfo(
        "hallucination_elimination",
        "幻觉消除 Agent",
        "hallucination_elimination",
        "正在核查内容",
    ),
    "practice_evaluation": AgentInfo(
        "practice_evaluation",
        "实训评估 Agent",
        "practice_evaluation",
        "正在评估实训结果",
    ),
}


NODE_AGENT_MAP: dict[str, str] = {
    "input_router": "task_dispatch",
    "generation_router": "task_dispatch",
    "learning_status_router": "task_dispatch",
    "rag_node": "knowledge_generation",
    "multi_generation_node": "knowledge_generation",
    "quiz_context_adapter_node": "knowledge_generation",
    "question_generator": "knowledge_generation",
    "lecture_generator": "knowledge_generation",
    "practice_guide_generator": "knowledge_generation",
    "qa_answer_generator": "knowledge_generation",
    "chapter_manifest_loader_node": "knowledge_generation",
    "knowledge_gap_loader_node": "knowledge_generation",
    "gap_focus_analysis_node": "knowledge_generation",
    "chapter_resource_loader_node": "knowledge_generation",
    "quiz_adaptation_context_node": "knowledge_generation",
    "progress_rag_planner_node": "knowledge_generation",
    "progress_patch_rag_node": "knowledge_generation",
    "progress_quiz_rag_node": "knowledge_generation",
    "progress_patch_generation_node": "knowledge_generation",
    "quiz_blueprint_node": "knowledge_generation",
    "quiz_blueprint_parser_node": "knowledge_generation",
    "quiz_typed_generation_node": "knowledge_generation",
    "quiz_schema_normalizer_node": "knowledge_generation",
    "quiz_strategy_node": "knowledge_generation",
    "course_resource_quiz_selection_node": "knowledge_generation",
    "course_resource_quiz_persistence_node": "knowledge_generation",
    "progress_quiz_generation_node": "knowledge_generation",
    "quiz_balance_review_node": "knowledge_generation",
    "progress_quiz_storage_node": "knowledge_generation",
    "quiz_material_adapter_node": "knowledge_generation",
    "evidence_retrieval_node": "knowledge_generation",
    "learning_path_resolver_node": "learning_management",
    "progress_advance_node": "learning_management",
    "quiz_feedback_context_loader_node": "learning_management",
    "qa_feedback_context_loader_node": "learning_management",
    "feedback_profile_context_loader_node": "learning_management",
    "feedback_node": "learning_management",
    "profile_assessment_review_node": "learning_management",
    "profile_assessment_apply_node": "learning_management",
    "personalization_node": "personalized_generation",
    "rewrite_node": "personalized_generation",
    "verification_prepare_node": "hallucination_elimination",
    "claim_proposer_node": "hallucination_elimination",
    "risk_normalizer_node": "hallucination_elimination",
    "evidence_selector_node": "hallucination_elimination",
    "claim_checker_node": "hallucination_elimination",
    "verification_router": "hallucination_elimination",
    "verification_query_planner_node": "hallucination_elimination",
    "safe_reject_node": "hallucination_elimination",
    "verified_persistence_node": "hallucination_elimination",
    "workpiece_standard_loader_node": "practice_evaluation",
    "operation_submission_loader_node": "practice_evaluation",
    "submission_validation_node": "practice_evaluation",
    "vl_analysis_node": "practice_evaluation",
    "measurement_compare_node": "practice_evaluation",
    "operation_review_node": "practice_evaluation",
    "operation_profile_update_node": "practice_evaluation",
    "cnc_exercise_loader_node": "practice_evaluation",
    "cnc_submission_loader_node": "practice_evaluation",
    "cnc_input_normalizer_node": "practice_evaluation",
    "hnc_semantic_conversion_node": "practice_evaluation",
    "cncjs_preview_node": "practice_evaluation",
    "hnc_raw_code_check_node": "practice_evaluation",
    "cnc_expected_result_check_node": "practice_evaluation",
    "cnc_result_merger_node": "practice_evaluation",
    "cnc_answer_snapshot_node": "practice_evaluation",
    "cnc_diagnosis_node": "practice_evaluation",
    "cnc_feedback_profile_update_node": "practice_evaluation",
}


NODE_ACTIVITY_TEXT: dict[str, str] = {
    "input_router": "正在识别任务意图",
    "generation_router": "正在选择生成路径",
    "learning_status_router": "正在选择学情路径",
    "feedback_profile_context_loader_node": "正在加载学习画像",
    "rag_node": "正在检索知识库",
    "progress_rag_planner_node": "正在规划检索问题",
    "quiz_context_adapter_node": "正在整理测验上下文",
    "quiz_blueprint_node": "正在规划测验题比例",
    "quiz_blueprint_parser_node": "正在解析测验蓝图",
    "quiz_typed_generation_node": "正在生成多题型测验",
    "quiz_schema_normalizer_node": "正在校验题目结构",
    "course_resource_quiz_persistence_node": "正在保存课程题库测验",
    "progress_quiz_generation_node": "正在生成章节测验",
    "quiz_balance_review_node": "正在审查测验题比例",
    "quiz_material_adapter_node": "正在整理测验材料",
    "personalization_node": "正在融合个性化材料",
    "rewrite_node": "正在重写存疑内容",
    "claim_checker_node": "正在核查事实声明",
    "verification_router": "正在决定内容是否放行",
    "cnc_diagnosis_node": "正在生成仿真诊断",
    "cnc_expected_result_check_node": "正在核对仿真预期结果",
    "vl_analysis_node": "正在分析工件图片",
    "operation_review_node": "正在生成上机审查结果",
    "profile_assessment_review_node": "正在审核画像证据",
    "profile_assessment_apply_node": "正在更新学习画像",
}


def agent_for_node(node_id: str) -> AgentInfo:
    agent_id = NODE_AGENT_MAP[node_id]
    return AGENT_REGISTRY[agent_id]


def activity_for_node(node_id: str) -> str:
    return NODE_ACTIVITY_TEXT.get(node_id) or agent_for_node(node_id).activity_text


def registered_graph_node_names(compiled_graph: Any) -> list[str]:
    graph = compiled_graph.get_graph()
    names = []
    for name in graph.nodes:
        if name in {"__start__", "__end__"}:
            continue
        names.append(str(name))
    return sorted(names)
