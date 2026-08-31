from __future__ import annotations

from typing import Any, TypedDict


ContentType = str


class RuntimeState(TypedDict, total=False):
    """Runtime-only dependency injection fields used by tests and demos."""

    _model: Any
    _feedback_model: Any
    _generation_model: Any
    _personalization_model: Any
    _rag_llm: Any
    _rag_retriever: Any
    _vl_model: Any
    _review_model: Any
    _progress_model: Any
    _verification_model: Any
    _profile_path: str
    _storage_root: str
    _course_resource_root: str
    _diagnosis_model: Any
    _cncjs_client: Any


class InputState(TypedDict, total=False):
    api_version: str
    request_id: str
    user_id: str
    course_id: str
    path_id: str
    path_version: str
    assignment_updated_at: str
    learner_level: str
    learner_profile: dict[str, Any]
    latest_scores: dict[str, float]
    learning_progress: dict[str, Any]
    chapter_id: str
    task_id: str
    submission_id: str
    raw_prompt: str
    task_draft: str
    source_code: str
    content_type: ContentType
    quiz_question_count: int
    quiz_blueprint_input: dict[str, Any]
    retry_count: int
    export_formats: list[str]
    options: dict[str, Any]


class InputRoutingState(TypedDict, total=False):
    input_route: str
    learning_status_intent: str
    learning_status_route: str


class InputUnderstandingState(TypedDict, total=False):
    task: str
    rag_questions: list[str]
    llm_raw_output: str
    task_constraints: dict[str, Any]


class RagState(TypedDict, total=False):
    rag_package: dict[str, Any]
    rag_llm_raw_output: str


class GenerationState(TypedDict, total=False):
    generation_route: str
    stage_generation_prompts: dict[str, str]
    qa_generation_prompt: str
    quiz_generation_prompt: str
    lecture_generation_prompt: str
    practice_generation_prompt: str
    generated_content: dict[str, Any]
    generated_materials: dict[str, Any]
    generated_question_content: dict[str, Any]
    generated_lecture_content: dict[str, Any]
    generated_practice_guide_content: dict[str, Any]
    generated_qa_content: dict[str, Any]
    final_output: dict[str, Any]
    final_materials: dict[str, Any]
    final_question_output: dict[str, Any]
    final_lecture_output: dict[str, Any]
    final_practice_guide_output: dict[str, Any]
    final_qa_output: dict[str, Any]


class PersonalizationState(TypedDict, total=False):
    profile_md_ref: str
    profile_md_content: str
    personalized_output: dict[str, Any]
    personalized_question_output: dict[str, Any]
    personalized_lecture_output: dict[str, Any]
    personalized_practice_guide_output: dict[str, Any]
    personalized_qa_output: dict[str, Any]
    personalization_llm_raw_outputs: dict[str, str]
    profile_update_suggestions: dict[str, Any]
    profile_evidence_packet: dict[str, Any]
    profile_assessment_review_result: dict[str, Any]
    personalization_locked_material_types: list[str]


class VerificationState(TypedDict, total=False):
    verification_materials: dict[str, dict[str, Any]]
    verification_claims: list[dict[str, Any]]
    claim_checks: list[dict[str, Any]]
    verification_summary: dict[str, Any]
    verification_decision: str
    verification_queries: list[str]
    verification_extra_evidence: list[dict[str, Any]]
    verification_retrieval_count: int
    verification_rewrite_count: int
    verified_output: dict[str, Any]
    verified_materials: dict[str, Any]
    verification_history: list[dict[str, Any]]
    verification_error: dict[str, Any]
    claim_evidence_map: dict[str, list[str]]
    selected_verification_evidence: list[dict[str, Any]]
    evidence_selector_raw_output: str
    verification_query_planner_raw_output: str


class ProfileToolState(TypedDict, total=False):
    profile_context: dict[str, Any]
    profile_context_load_result: dict[str, Any]
    feedback_llm_raw_output: str
    profile_update_result: dict[str, Any]
    feedback_result: dict[str, Any]
    feedback_assessment: dict[str, Any]
    progress_advance_result: dict[str, Any]
    learning_recommendations: dict[str, Any]
    learning_recommendation_refresh_result: dict[str, Any]


class FeedbackContextState(TypedDict, total=False):
    feedback_source_type: str
    feedback_source_ids: dict[str, Any]
    feedback_context: dict[str, Any]
    feedback_context_paths: dict[str, str]
    feedback_context_load_result: dict[str, Any]
    question_scope: str
    attempt_id: str
    session_id: str


class LearningStageState(TypedDict, total=False):
    progress_profile_context: dict[str, Any]
    path_assignment: dict[str, Any] | None
    path_id: str
    path_version: str
    assignment_updated_at: str
    learner_level: str
    generation_policy: dict[str, Any]
    learning_path_resolution: dict[str, Any]
    learning_path_resource_root: str | None
    previous_chapter_id: str | None
    learning_stage: dict[str, Any]
    next_chapter_id: str | None


class ChapterManifestState(TypedDict, total=False):
    chapter_manifest: dict[str, Any]
    chapter_focus: dict[str, Any]
    required_material_types: list[str]
    chapter_asset_index: dict[str, Any]
    missing_assets: list[dict[str, Any]]
    effective_chapter_config: dict[str, Any]


class CourseResourceState(TypedDict, total=False):
    learning_path: dict[str, Any]
    course_resource_bundle: dict[str, Any]
    manual_lecture_content: str
    manual_practice_content: str
    chapter_base_materials: dict[str, Any]
    chapter_resource_paths: dict[str, str]
    chapter_resource_load_result: dict[str, Any]
    reference_quiz: dict[str, Any]
    operation_task_bundle: dict[str, Any]
    standard_workpiece_spec: dict[str, Any]


class ProgressBranchState(TypedDict, total=False):
    pipeline_type: str
    knowledge_gap_files: dict[str, str]
    knowledge_gap_documents: dict[str, Any]
    knowledge_gap_events: list[dict[str, Any]]
    knowledge_gap_load_result: dict[str, Any]
    gap_focus_analysis: dict[str, Any]
    related_knowledge_gaps: list[dict[str, Any]]
    patch_target_points: list[dict[str, Any]]
    quiz_relevant_focus_points: list[dict[str, Any]]
    knowledge_gap_patch_plan: dict[str, Any]
    gap_focus_analysis_raw_output: str
    user_quantitative_profile: dict[str, Any]
    quiz_difficulty_policy: dict[str, Any]
    quiz_reference_examples: dict[str, Any]
    quiz_adaptation_result: dict[str, Any]
    quiz_context_adapter_result: dict[str, Any]
    quiz_blueprint_parse_result: dict[str, Any]
    quiz_type_policy: dict[str, float]
    quiz_generation_blueprint: dict[str, Any]
    quiz_blueprint_slots: list[dict[str, Any]]
    quiz_blueprint_result: dict[str, Any]
    quiz_strategy: str
    quiz_source_mode: str
    quiz_strategy_result: dict[str, Any]
    quiz_bank: list[dict[str, Any]]
    quiz_selection_policy: dict[str, Any]
    selected_quiz_questions: list[dict[str, Any]]
    quiz_selection_result: dict[str, Any]
    course_resource_quiz_persistence_result: dict[str, Any]
    progress_patch_rag_queries: list[str]
    progress_quiz_rag_queries: list[str]
    progress_rag_plan: dict[str, Any]
    patch_rag_package: dict[str, Any]
    patch_rag_evidence: list[dict[str, Any]]
    patch_rag_llm_raw_output: str
    quiz_rag_package: dict[str, Any]
    quiz_rag_evidence: list[dict[str, Any]]
    quiz_rag_llm_raw_output: str
    lecture_patch_content: dict[str, Any]
    practice_patch_content: dict[str, Any]
    progress_patch_materials: dict[str, Any]
    patch_generation_raw_output: str
    progress_quiz_output: dict[str, Any]
    progress_quiz_generation_raw_output: str
    typed_quiz_output: dict[str, Any]
    typed_quiz_generation_raw_output: str
    quiz_schema_validation_result: dict[str, Any]
    balanced_quiz_questions: list[dict[str, Any]]
    quiz_balance_review_result: dict[str, Any]
    saved_progress_quiz_artifact: dict[str, Any]
    progress_quiz_artifact_id: str
    progress_quiz_artifact_paths: dict[str, str]
    progress_personalized_materials: dict[str, Any]
    progress_personalized_lecture_output: dict[str, Any]
    progress_personalized_practice_output: dict[str, Any]
    progress_personalization_raw_output: str


class OperationReviewState(TypedDict, total=False):
    operation_review_intent: str
    workpiece_id: str
    uploaded_images: list[dict[str, Any]]
    measurement_params: dict[str, Any]
    static_task_ref: str
    review_rules: dict[str, Any]
    operation_loaded_submission: dict[str, Any]
    operation_task_manifest: dict[str, Any]
    operation_submission_load_result: dict[str, Any]
    operation_review_paths: dict[str, str]
    submission_validation_result: dict[str, Any]
    vl_analysis_result: dict[str, Any]
    measurement_comparison_result: dict[str, Any]
    rule_based_review_decision: dict[str, Any]
    operation_review_result: dict[str, Any]
    operation_profile_update_suggestions: dict[str, Any]
    operation_profile_update_result: dict[str, Any]


class ArchiveToolState(TypedDict, total=False):
    saved_outputs: dict[str, Any]
    artifact_id: str
    artifact_paths: dict[str, str]
    saved_artifact: dict[str, Any]
    question_artifact_id: str
    question_artifact_paths: dict[str, str]
    saved_question_artifact: dict[str, Any]
    lecture_artifact_id: str
    lecture_artifact_paths: dict[str, str]
    saved_lecture_artifact: dict[str, Any]
    practice_guide_artifact_id: str
    practice_guide_artifact_paths: dict[str, str]
    saved_practice_guide_artifact: dict[str, Any]
    qa_artifact_id: str
    qa_artifact_paths: dict[str, str]
    saved_qa_artifact: dict[str, Any]
    quiz_attempt: dict[str, Any]
    qa_session_id: str
    qa_context: dict[str, Any]
    qa_messages: list[dict[str, Any]]


class OverallState(
    RuntimeState,
    InputState,
    InputRoutingState,
    InputUnderstandingState,
    RagState,
    GenerationState,
    PersonalizationState,
    VerificationState,
    ProfileToolState,
    FeedbackContextState,
    LearningStageState,
    ChapterManifestState,
    CourseResourceState,
    ProgressBranchState,
    OperationReviewState,
    ArchiveToolState,
    total=False,
):
    """Shared LangGraph state assembled from focused state slices."""

    cnc_feedback_intent: str
    cnc_task_bundle: dict[str, Any]
    cnc_simulation_rules: dict[str, Any]
    cnc_submission_load_result: dict[str, Any]
    cnc_feedback_paths: dict[str, str]
    hnc_code: str
    normalized_code: str
    standard_gcode: str
    hnc_semantic_conversion_result: dict[str, Any]
    cncjs_preview_result: dict[str, Any]
    hnc_raw_check_result: dict[str, Any]
    cnc_expected_result_check: dict[str, Any]
    cnc_merged_review_result: dict[str, Any]
    cnc_answer_snapshot: dict[str, Any]
    cnc_diagnosis_result: dict[str, Any]
    cnc_profile_update_suggestions: dict[str, Any]
    cnc_profile_update_result: dict[str, Any]
