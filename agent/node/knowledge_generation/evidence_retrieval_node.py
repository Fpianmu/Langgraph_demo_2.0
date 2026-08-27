from __future__ import annotations

from agent.node.node_logging import log_node_runtime
from agent.node.verification_utils import dedupe_evidence
from agent.rag.schemas import RagPackage
from agent.rag.simple_retriever import SimpleResourceRetriever
from agent.state import OverallState


@log_node_runtime("evidence_retrieval_node")
def evidence_retrieval_node(state: OverallState) -> OverallState:
    queries = [str(item).strip() for item in (state.get("verification_queries") or []) if str(item).strip()]
    retriever = state.get("_rag_retriever") or SimpleResourceRetriever()
    package = retriever.retrieve(queries)
    if isinstance(package, RagPackage):
        new_items = package.model_dump(mode="json").get("evidence", [])
    elif isinstance(package, dict):
        new_items = package.get("evidence") or []
    else:
        new_items = []
    merged = dedupe_evidence([*(state.get("verification_extra_evidence") or []), *new_items])
    return {
        "verification_extra_evidence": merged,
        "verification_retrieval_count": int(state.get("verification_retrieval_count") or 0) + 1,
    }
