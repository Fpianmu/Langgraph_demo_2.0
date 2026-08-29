export type ContentType =
  | "quiz"
  | "qa"
  | "lecture"
  | "practice"
  | "feedback"
  | "next_step";

export type ScoreMap = {
  theory: number;
  safety: number;
  operation: number;
  [key: string]: number;
};

export type LearnerProfile = {
  background: string;
  level: "beginner" | "intermediate" | "advanced";
  preference: string;
  [key: string]: string | string[];
};

export type AgentRequest = {
  api_version: "v2";
  request_id: string;
  user_id: string;
  course_id: string;
  chapter_id?: string;
  raw_prompt: string;
  task?: string;
  content_type: ContentType;
  latest_scores: ScoreMap;
  learner_profile: LearnerProfile;
  learning_progress?: Record<string, unknown>;
  quiz_blueprint_input?: Record<string, unknown>;
  profile_md_ref?: string;
  profile_md_version?: string;
  profile_md_hash?: string;
  qa_session_id?: string;
  options: {
    max_retries: number;
    trace_level: "debug" | "normal";
    return_rag_package: boolean;
  };
};

export type QuizQuestion = {
  stem: string;
  question_type?:
    | "single_choice"
    | "true_false"
    | "cloze"
    | "short_answer";
  options: string[];
  answer: string;
  reference_answer?: string;
  explanation: string;
  concise_explanation?: string;
  detailed_explanation?: string;
  difficulty: string;
  points?: number;
  scoring_rubric?: {
    key_points?: Array<{
      id?: string;
      description: string;
      points: number;
    }>;
    required_terms?: string[];
  };
  /** Metadata used by deterministic capability scoring. */
  capability_dimension?: string;
  knowledge_point?: string;
  source_refs?: string[];
  rag_chunk_ids?: string[];
  /** Whether sources were attached to this item or inherited from the batch. */
  source_grounding_scope?: "question" | "session" | "none";
  /** Backend persistence references. They never affect question rendering. */
  backend_artifact_id?: string;
  backend_question_id?: string;
};

export type QaPayload = {
  question: string;
  answer: string;
  follow_ups?: string[];
};

export type QuizPayload = {
  questions: QuizQuestion[];
};

export type AgentTrace = {
  node: string;
  status: string;
  summary: string;
  input_keys?: string[];
  output_keys?: string[];
  error?: string | null;
  retry_reason?: string | null;
};

export type ProfilePatch = {
  path: string;
  op: "replace" | "add" | "remove";
  value: unknown;
  reason: string;
  confidence: number;
};

export type ScorePatch = {
  dimension: string;
  op: "add" | "replace";
  value: number;
  reason: string;
  confidence: number;
};

export type ProfileUpdateSuggestions = {
  confidence?: number;
  manual_review_required?: boolean;
  md_patches?: ProfilePatch[];
  score_patches?: ScorePatch[];
  rationale?: string[];
};

export type AgentResponse = {
  api_version: "v2";
  request_id: string;
  status:
    | "success"
    | "need_more_evidence"
    | "content_rejected"
    | "safety_rejected"
    | "validation_error"
    | "internal_error";
  content_type: ContentType;
  task: string;
  final_output: {
    meta?: Record<string, unknown>;
    title?: string;
    summary?: string;
    payload?: QaPayload | QuizPayload | Record<string, unknown>;
    evidence_refs?: string[];
    safety_notes?: string[];
    next_actions?: string[];
  } | null;
  rag_package: {
    query?: string;
    answer?: string;
    evidence?: Array<{
      text?: string;
      source_doc?: string;
      source_file?: string;
      chunk_id?: string;
      score?: number;
      page_label?: string;
    }>;
    citations?: Array<{
      source_doc?: string;
      source_file?: string;
      chunk_id?: string;
      label?: string;
    }>;
    confidence?: number;
    warnings?: string[];
    next_action?: string;
    knowledge_base_version?: string;
    retrieval_mode?: string;
    embedding_model?: string;
  } | null;
  check_report: {
    status?: string;
    unsupported_claims?: string[];
    evidence_coverage?: number;
    summary?: string;
    retry_suggestion?: string | null;
  } | null;
  safety_report: {
    status?: string;
    risk_flags?: string[];
    unsafe_spans?: string[];
    summary?: string;
    retry_suggestion?: string | null;
  } | null;
  profile_update_suggestions: ProfileUpdateSuggestions;
  agent_trace: AgentTrace[];
  error_type: string | null;
  retry_count: number;
  qa_session_id?: string;
  saved_outputs?: Record<string, unknown>;
  profile_md_ref?: string;
  final_materials?: Record<string, unknown>;
  personalized_qa_output?: Record<string, unknown>;
  personalized_question_output?: Record<string, unknown>;
  personalized_lecture_output?: Record<string, unknown>;
  final_qa_output?: Record<string, unknown>;
  final_question_output?: Record<string, unknown>;
  final_lecture_output?: Record<string, unknown>;
  lecture_artifact_paths?: Record<string, unknown>;
  saved_lecture_artifact?: Record<string, unknown>;
};

export type OrchestratorInput = {
  userId: string;
  courseId: string;
  prompt: string;
  contentType: ContentType;
  scores: ScoreMap;
  profile: LearnerProfile;
  task?: string;
  chapterId?: string;
  qaSessionId?: string;
  learningProgress?: Record<string, unknown>;
  quizBlueprint?: Record<string, unknown>;
};
