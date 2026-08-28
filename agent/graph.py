from __future__ import annotations

import logging
import sys
from pathlib import Path

from langgraph.graph import END, START, StateGraph

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.node.task_dispatch.generation_router import generation_router
from agent.node.hallucination_elimination.claim_checker_node import claim_checker_node
from agent.node.hallucination_elimination.claim_proposer_node import claim_proposer_node
from agent.node.knowledge_generation.evidence_retrieval_node import evidence_retrieval_node
from agent.node.hallucination_elimination.evidence_selector_node import evidence_selector_node
from agent.node.knowledge_generation.generators import (
    lecture_generator,
    practice_guide_generator,
    qa_answer_generator,
    question_generator,
)
from agent.node.knowledge_generation.chapter_manifest_loader_node import chapter_manifest_loader_node
from agent.node.learning_management.feedback_node import feedback_node
from agent.node.learning_management.feedback_context_loader_nodes import qa_feedback_context_loader_node, quiz_feedback_context_loader_node
from agent.node.learning_management.feedback_profile_context_loader_node import feedback_profile_context_loader_node
from agent.node.learning_management.profile_assessment_nodes import (
    profile_assessment_apply_node,
    profile_assessment_review_node,
)
from agent.node.task_dispatch.learning_status_router import learning_status_router
from agent.node.learning_management.learning_path_resolver_node import learning_path_resolver_node
from agent.node.knowledge_generation.multi_generation_node import multi_generation_node
from agent.node.practice_evaluation.operation_review_nodes import (
    measurement_compare_node,
    operation_profile_update_node,
    operation_review_node,
    operation_submission_loader_node,
    submission_validation_node,
    vl_analysis_node,
    workpiece_standard_loader_node,
)
from agent.node.practice_evaluation.cnc_simulation_nodes import (
    cnc_answer_snapshot_node,
    cnc_diagnosis_node,
    cnc_exercise_loader_node,
    cnc_expected_result_check_node,
    cnc_feedback_profile_update_node,
    cnc_input_normalizer_node,
    cnc_result_merger_node,
    cnc_submission_loader_node,
    cncjs_preview_node,
    hnc_raw_code_check_node,
    hnc_semantic_conversion_node,
)
from agent.node.personalized_generation.personalization_node import personalization_node
from agent.node.knowledge_generation.progress_branch_nodes import (
    chapter_resource_loader_node,
    course_resource_quiz_persistence_node,
    course_resource_quiz_selection_node,
    gap_focus_analysis_node,
    knowledge_gap_loader_node,
    quiz_blueprint_parser_node,
    quiz_balance_review_node,
    quiz_blueprint_node,
    quiz_context_adapter_node,
    quiz_material_adapter_node,
    quiz_schema_normalizer_node,
    quiz_typed_generation_node,
    progress_patch_generation_node,
    progress_patch_rag_node,
    progress_quiz_generation_node,
    progress_quiz_rag_node,
    progress_quiz_storage_node,
    progress_rag_planner_node,
    quiz_strategy_node,
    quiz_adaptation_context_node,
)
from agent.node.learning_management.progress_advance_node import progress_advance_node
from agent.node.knowledge_generation.rag_node import rag_node
from agent.node.hallucination_elimination.risk_normalizer_node import risk_normalizer_node
from agent.node.personalized_generation.rewrite_node import rewrite_node
from agent.node.hallucination_elimination.safe_reject_node import safe_reject_node
from agent.node.task_dispatch.input_router import input_router
from agent.state import OverallState
from agent.node.hallucination_elimination.verification_prepare_node import verification_prepare_node
from agent.node.hallucination_elimination.verification_query_planner_node import verification_query_planner_node
from agent.node.hallucination_elimination.verification_router import verification_router
from agent.node.hallucination_elimination.verified_persistence_node import verified_persistence_node


LOGGER = logging.getLogger("agent.graph")


def build_graph():
    LOGGER.info("building agent graph with learning status nodes: learning_status_router, feedback_node, progress_advance_node")
    builder = StateGraph(state_schema=OverallState)
    builder.add_node("input_router", input_router, destinations=("rag_node", "learning_status_router"))
    builder.add_node("rag_node", rag_node)
    builder.add_node(
        "generation_router",
        generation_router,
        destinations=(
            "multi_generation_node",
            "quiz_context_adapter_node",
            "question_generator",
            "lecture_generator",
            "practice_guide_generator",
            "qa_answer_generator",
        ),
    )
    builder.add_node("multi_generation_node", multi_generation_node)
    builder.add_node("quiz_context_adapter_node", quiz_context_adapter_node)
    builder.add_node("question_generator", question_generator)
    builder.add_node("lecture_generator", lecture_generator)
    builder.add_node("practice_guide_generator", practice_guide_generator)
    builder.add_node("qa_answer_generator", qa_answer_generator)

    # Learning status branch: feedback proposes evidence, profile assessment middleware writes profile data.
    builder.add_node(
        "learning_status_router",
        learning_status_router,
        destinations=(
            "feedback_node",
            "feedback_profile_context_loader_node",
            "learning_path_resolver_node",
            "cnc_exercise_loader_node",
            "workpiece_standard_loader_node",
            "quiz_feedback_context_loader_node",
            "qa_feedback_context_loader_node",
        ),
    )
    builder.add_node("quiz_feedback_context_loader_node", quiz_feedback_context_loader_node)
    builder.add_node("qa_feedback_context_loader_node", qa_feedback_context_loader_node)
    builder.add_node("feedback_profile_context_loader_node", feedback_profile_context_loader_node)
    builder.add_node("feedback_node", feedback_node)
    builder.add_node("profile_assessment_review_node", profile_assessment_review_node)
    builder.add_node("profile_assessment_apply_node", profile_assessment_apply_node)
    builder.add_node("learning_path_resolver_node", learning_path_resolver_node, destinations=("progress_advance_node",))
    builder.add_node("progress_advance_node", progress_advance_node, destinations=("chapter_manifest_loader_node",))
    builder.add_node("chapter_manifest_loader_node", chapter_manifest_loader_node)
    builder.add_node("knowledge_gap_loader_node", knowledge_gap_loader_node)
    builder.add_node("gap_focus_analysis_node", gap_focus_analysis_node)
    builder.add_node("chapter_resource_loader_node", chapter_resource_loader_node)
    builder.add_node("quiz_adaptation_context_node", quiz_adaptation_context_node)
    builder.add_node("progress_rag_planner_node", progress_rag_planner_node)
    builder.add_node("progress_patch_rag_node", progress_patch_rag_node)
    builder.add_node("progress_quiz_rag_node", progress_quiz_rag_node)
    builder.add_node("progress_patch_generation_node", progress_patch_generation_node)
    builder.add_node("quiz_blueprint_node", quiz_blueprint_node)
    builder.add_node("quiz_blueprint_parser_node", quiz_blueprint_parser_node)
    builder.add_node(
        "quiz_strategy_node",
        quiz_strategy_node,
        destinations=("progress_quiz_rag_node", "course_resource_quiz_selection_node"),
    )
    builder.add_node("course_resource_quiz_selection_node", course_resource_quiz_selection_node)
    builder.add_node("course_resource_quiz_persistence_node", course_resource_quiz_persistence_node)
    builder.add_node("progress_quiz_generation_node", progress_quiz_generation_node)
    builder.add_node("quiz_typed_generation_node", quiz_typed_generation_node)
    builder.add_node("quiz_schema_normalizer_node", quiz_schema_normalizer_node)
    builder.add_node(
        "quiz_balance_review_node",
        quiz_balance_review_node,
        destinations=("progress_quiz_storage_node", "quiz_material_adapter_node"),
    )
    builder.add_node("quiz_material_adapter_node", quiz_material_adapter_node)
    builder.add_node("progress_quiz_storage_node", progress_quiz_storage_node)
    builder.add_node("personalization_node", personalization_node)
    builder.add_node("verification_prepare_node", verification_prepare_node)
    builder.add_node("claim_proposer_node", claim_proposer_node)
    builder.add_node("risk_normalizer_node", risk_normalizer_node)
    builder.add_node("evidence_selector_node", evidence_selector_node)
    builder.add_node("claim_checker_node", claim_checker_node)
    builder.add_node(
        "verification_router",
        verification_router,
        destinations=(
            "verified_persistence_node",
            "verification_query_planner_node",
            "rewrite_node",
            "safe_reject_node",
        ),
    )
    builder.add_node("verification_query_planner_node", verification_query_planner_node)
    builder.add_node("evidence_retrieval_node", evidence_retrieval_node)
    builder.add_node("rewrite_node", rewrite_node)
    builder.add_node("safe_reject_node", safe_reject_node)
    builder.add_node("verified_persistence_node", verified_persistence_node)
    builder.add_node("workpiece_standard_loader_node", workpiece_standard_loader_node)
    builder.add_node("operation_submission_loader_node", operation_submission_loader_node)
    builder.add_node("submission_validation_node", submission_validation_node)
    builder.add_node("vl_analysis_node", vl_analysis_node)
    builder.add_node("measurement_compare_node", measurement_compare_node)
    builder.add_node("operation_review_node", operation_review_node)
    builder.add_node("operation_profile_update_node", operation_profile_update_node)
    builder.add_node("cnc_exercise_loader_node", cnc_exercise_loader_node, destinations=("cnc_submission_loader_node",))
    builder.add_node("cnc_submission_loader_node", cnc_submission_loader_node)
    builder.add_node("cnc_input_normalizer_node", cnc_input_normalizer_node)
    builder.add_node("hnc_semantic_conversion_node", hnc_semantic_conversion_node)
    builder.add_node("cncjs_preview_node", cncjs_preview_node)
    builder.add_node("hnc_raw_code_check_node", hnc_raw_code_check_node)
    builder.add_node("cnc_expected_result_check_node", cnc_expected_result_check_node)
    builder.add_node("cnc_result_merger_node", cnc_result_merger_node)
    builder.add_node("cnc_answer_snapshot_node", cnc_answer_snapshot_node)
    builder.add_node("cnc_diagnosis_node", cnc_diagnosis_node)
    builder.add_node("cnc_feedback_profile_update_node", cnc_feedback_profile_update_node)
    
    builder.add_edge(START, "input_router")
    builder.add_edge("rag_node", "generation_router")
    builder.add_edge("multi_generation_node", "personalization_node")
    builder.add_edge("quiz_context_adapter_node", "quiz_blueprint_parser_node")
    builder.add_edge("question_generator", "personalization_node")
    builder.add_edge("lecture_generator", "personalization_node")
    builder.add_edge("practice_guide_generator", "personalization_node")
    builder.add_edge("qa_answer_generator", "personalization_node")
    builder.add_edge("quiz_feedback_context_loader_node", "profile_assessment_review_node")
    builder.add_edge("qa_feedback_context_loader_node", "feedback_profile_context_loader_node")
    builder.add_edge("feedback_profile_context_loader_node", "feedback_node")
    builder.add_edge("feedback_node", "profile_assessment_review_node")
    builder.add_edge("profile_assessment_review_node", "profile_assessment_apply_node")
    builder.add_edge("profile_assessment_apply_node", END)
    builder.add_edge("chapter_manifest_loader_node", "knowledge_gap_loader_node")
    builder.add_edge("knowledge_gap_loader_node", "gap_focus_analysis_node")
    builder.add_edge("gap_focus_analysis_node", "chapter_resource_loader_node")
    builder.add_edge("chapter_resource_loader_node", "quiz_adaptation_context_node")
    builder.add_edge("quiz_adaptation_context_node", "progress_rag_planner_node")
    builder.add_edge("progress_rag_planner_node", "progress_patch_rag_node")
    builder.add_edge("progress_patch_rag_node", "progress_patch_generation_node")
    builder.add_edge("progress_patch_generation_node", "quiz_strategy_node")
    builder.add_edge("progress_quiz_rag_node", "quiz_blueprint_node")
    builder.add_edge("quiz_blueprint_parser_node", "quiz_typed_generation_node")
    builder.add_edge("quiz_blueprint_node", "quiz_typed_generation_node")
    builder.add_edge("quiz_typed_generation_node", "quiz_schema_normalizer_node")
    builder.add_edge("course_resource_quiz_selection_node", "course_resource_quiz_persistence_node")
    builder.add_edge("course_resource_quiz_persistence_node", END)
    builder.add_edge("progress_quiz_generation_node", "quiz_schema_normalizer_node")
    builder.add_edge("quiz_schema_normalizer_node", "quiz_balance_review_node")
    builder.add_edge("quiz_material_adapter_node", "personalization_node")
    builder.add_edge("progress_quiz_storage_node", "personalization_node")
    builder.add_edge("personalization_node", "verification_prepare_node")
    builder.add_edge("verification_prepare_node", "claim_proposer_node")
    builder.add_edge("claim_proposer_node", "risk_normalizer_node")
    builder.add_edge("risk_normalizer_node", "evidence_selector_node")
    builder.add_edge("evidence_selector_node", "claim_checker_node")
    builder.add_edge("claim_checker_node", "verification_router")
    builder.add_edge("verification_query_planner_node", "evidence_retrieval_node")
    builder.add_edge("evidence_retrieval_node", "claim_checker_node")
    builder.add_edge("rewrite_node", "claim_proposer_node")
    builder.add_edge("verified_persistence_node", END)
    builder.add_edge("safe_reject_node", END)
    builder.add_edge("workpiece_standard_loader_node", "operation_submission_loader_node")
    builder.add_edge("operation_submission_loader_node", "submission_validation_node")
    builder.add_edge("submission_validation_node", "vl_analysis_node")
    builder.add_edge("vl_analysis_node", "measurement_compare_node")
    builder.add_edge("measurement_compare_node", "operation_review_node")
    builder.add_edge("operation_review_node", "operation_profile_update_node")
    builder.add_edge("operation_profile_update_node", "profile_assessment_review_node")
    builder.add_edge("cnc_exercise_loader_node", "cnc_submission_loader_node")
    builder.add_edge("cnc_submission_loader_node", "cnc_input_normalizer_node")
    builder.add_edge("cnc_input_normalizer_node", "hnc_semantic_conversion_node")
    builder.add_edge("hnc_semantic_conversion_node", "cncjs_preview_node")
    builder.add_edge("cncjs_preview_node", "hnc_raw_code_check_node")
    builder.add_edge("hnc_raw_code_check_node", "cnc_expected_result_check_node")
    builder.add_edge("cnc_expected_result_check_node", "cnc_result_merger_node")
    builder.add_edge("cnc_result_merger_node", "cnc_answer_snapshot_node")
    builder.add_edge("cnc_answer_snapshot_node", "cnc_diagnosis_node")
    builder.add_edge("cnc_diagnosis_node", "cnc_feedback_profile_update_node")
    builder.add_edge("cnc_feedback_profile_update_node", "profile_assessment_review_node")
    return builder.compile()


graph = build_graph()


if __name__ == "__main__":
    import json
    from agent.graph import graph

    result = graph.invoke(
        {
            "content_type": "qa",
            "request_id": "req_qa_001",
            "user_id": "user_001",
            "course_id": "cnc_lathe",
            "chapter_id": "1.1",
            "raw_prompt": "铣削内轮廓时，如果无法切线切入，如何确定法向切入点的最佳位置？",
        }
    )

    print(json.dumps(
        {
            "final_result": result.get("final_output"),
            "qa_session_id": result.get("qa_session_id"),
            "qa_artifact_paths": result.get("qa_artifact_paths"),
            "profile_md_ref": result.get("profile_md_ref"),
            "saved_outputs": result.get("saved_outputs"),
        },
        ensure_ascii=False,
        indent=2,
    ))

