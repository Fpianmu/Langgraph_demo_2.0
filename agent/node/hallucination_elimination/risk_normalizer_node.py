from __future__ import annotations

from agent.node.node_logging import log_node_runtime
from agent.state import OverallState


HIGH_RISK_MARKERS = ("转速", "进给", "切削深度", "阈值", "危险", "运行中", "不停机", "权限", "安全")


@log_node_runtime("risk_normalizer_node")
def risk_normalizer_node(state: OverallState) -> OverallState:
    normalized = []
    for claim in state.get("verification_claims") or []:
        if not isinstance(claim, dict):
            continue
        item = dict(claim)
        text = str(item.get("claim_text") or "")
        if item.get("claim_type") in {"numeric", "procedural", "safety", "answer_key"} or any(marker in text for marker in HIGH_RISK_MARKERS):
            item["risk_level"] = "high"
        item.setdefault("risk_level", "medium")
        normalized.append(item)
    return {"verification_claims": normalized}
