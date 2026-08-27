"""Agent graph nodes."""

from __future__ import annotations

import importlib
import sys


_LEGACY_MODULE_ALIASES = {
    "input_router": "agent.node.task_dispatch.input_router",
    "generation_router": "agent.node.task_dispatch.generation_router",
    "learning_status_router": "agent.node.task_dispatch.learning_status_router",
    "rag_node": "agent.node.knowledge_generation.rag_node",
    "multi_generation_node": "agent.node.knowledge_generation.multi_generation_node",
    "generators": "agent.node.knowledge_generation.generators",
    "chapter_manifest_loader_node": "agent.node.knowledge_generation.chapter_manifest_loader_node",
    "progress_branch_nodes": "agent.node.knowledge_generation.progress_branch_nodes",
    "evidence_retrieval_node": "agent.node.knowledge_generation.evidence_retrieval_node",
    "learning_path_resolver_node": "agent.node.learning_management.learning_path_resolver_node",
    "progress_advance_node": "agent.node.learning_management.progress_advance_node",
    "feedback_context_loader_nodes": "agent.node.learning_management.feedback_context_loader_nodes",
    "feedback_node": "agent.node.learning_management.feedback_node",
    "personalization_node": "agent.node.personalized_generation.personalization_node",
    "rewrite_node": "agent.node.personalized_generation.rewrite_node",
    "verification_prepare_node": "agent.node.hallucination_elimination.verification_prepare_node",
    "claim_proposer_node": "agent.node.hallucination_elimination.claim_proposer_node",
    "risk_normalizer_node": "agent.node.hallucination_elimination.risk_normalizer_node",
    "evidence_selector_node": "agent.node.hallucination_elimination.evidence_selector_node",
    "claim_checker_node": "agent.node.hallucination_elimination.claim_checker_node",
    "verification_router": "agent.node.hallucination_elimination.verification_router",
    "verification_query_planner_node": "agent.node.hallucination_elimination.verification_query_planner_node",
    "safe_reject_node": "agent.node.hallucination_elimination.safe_reject_node",
    "verified_persistence_node": "agent.node.hallucination_elimination.verified_persistence_node",
    "cnc_simulation_nodes": "agent.node.practice_evaluation.cnc_simulation_nodes",
    "operation_review_nodes": "agent.node.practice_evaluation.operation_review_nodes",
}


for legacy_name, target_module in _LEGACY_MODULE_ALIASES.items():
    legacy_full_name = f"{__name__}.{legacy_name}"
    if legacy_full_name not in sys.modules:
        sys.modules[legacy_full_name] = importlib.import_module(target_module)
