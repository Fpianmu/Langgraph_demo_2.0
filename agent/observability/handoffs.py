from __future__ import annotations

from dataclasses import dataclass

from agent.observability.registry import NODE_AGENT_MAP


@dataclass(frozen=True)
class HandoffMessage:
    from_agent: str
    to_agent: str
    display_text: str
    message_type: str
    detail: str


EXPLICIT_MESSAGES: dict[tuple[str, str], tuple[str, str, str]] = {
    ("input_router", "rag_node"): ("进入内容生成", "handoff", "任务调度已将请求交给知识检索与生成。"),
    ("input_router", "learning_status_router"): ("进入学情处理", "handoff", "任务调度已将请求交给学情路径。"),
    ("learning_status_router", "cnc_exercise_loader_node"): ("进入CNC仿真", "handoff", "开始处理代码仿真提交。"),
    ("learning_status_router", "workpiece_standard_loader_node"): (
        "进入上机审查",
        "handoff",
        "开始处理工件图片与测量数据。",
    ),
    ("progress_advance_node", "chapter_manifest_loader_node"): (
        "发送学习路径",
        "handoff",
        "学情管理已确定下一学习章节。",
    ),
    ("progress_quiz_storage_node", "personalization_node"): (
        "提交路径材料",
        "handoff",
        "基础学习路径材料已提交个性化融合。",
    ),
    ("personalization_node", "verification_prepare_node"): (
        "提交审查",
        "review_request",
        "个性化材料已提交事实核查。",
    ),
    ("verification_query_planner_node", "evidence_retrieval_node"): (
        "请求补充证据",
        "evidence_request",
        "幻觉消除需要补充候选证据。",
    ),
    ("evidence_retrieval_node", "claim_checker_node"): (
        "返回候选证据",
        "response",
        "知识检索已返回补充证据。",
    ),
    ("verification_router", "rewrite_node"): (
        "要求内容重写",
        "revision_request",
        "幻觉消除要求重写存疑内容。",
    ),
    ("rewrite_node", "claim_proposer_node"): (
        "返回重写内容",
        "response",
        "个性化生成已返回重写材料。",
    ),
}

GENERATOR_NODES = {
    "multi_generation_node",
    "question_generator",
    "lecture_generator",
    "practice_guide_generator",
    "qa_answer_generator",
}

SUPPRESSED_TRANSITIONS = {
    ("rag_node", "generation_router"),
}


def message_for_transition(source_node: str | None, target_node: str) -> HandoffMessage | None:
    if not source_node:
        return None
    if (source_node, target_node) in SUPPRESSED_TRANSITIONS:
        return None
    source_agent = NODE_AGENT_MAP.get(source_node)
    target_agent = NODE_AGENT_MAP.get(target_node)
    if source_agent and target_agent and source_agent == target_agent:
        return None
    explicit = EXPLICIT_MESSAGES.get((source_node, target_node))
    if explicit:
        from_agent = NODE_AGENT_MAP[source_node]
        to_agent = NODE_AGENT_MAP[target_node]
        display_text, message_type, detail = explicit
        return HandoffMessage(from_agent, to_agent, display_text, message_type, detail)
    if source_node in GENERATOR_NODES and target_node == "personalization_node":
        return HandoffMessage(
            "knowledge_generation",
            "personalized_generation",
            "提交基础材料",
            "handoff",
            "基础生成材料已提交个性化融合。",
        )
    if source_agent and target_agent and source_agent != target_agent:
        return HandoffMessage(source_agent, target_agent, "交接任务", "handoff", "任务进入下一 Agent。")
    return None
