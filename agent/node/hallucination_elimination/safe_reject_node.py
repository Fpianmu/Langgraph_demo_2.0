from __future__ import annotations

from copy import deepcopy

from agent.node.node_logging import log_node_runtime
from agent.node.verification_utils import get_review_materials, write_review_materials
from agent.state import OverallState


@log_node_runtime("safe_reject_node")
def safe_reject_node(state: OverallState) -> OverallState:
    materials = get_review_materials(state)
    rejected = {kind: _reject_material(kind, material) for kind, material in materials.items()}
    update = write_review_materials(state, rejected)
    if len(rejected) == 1 and "single" in rejected:
        update["verified_output"] = rejected["single"]
    else:
        update["verified_materials"] = rejected
    update["verification_decision"] = "safe_reject_node"
    return update


def _reject_material(kind: str, material: dict) -> dict:
    result = deepcopy(material)
    meta = result.setdefault("meta", {})
    if isinstance(meta, dict):
        meta["status"] = "rejected"
        meta["verification_status"] = "rejected"
    content_type = str(meta.get("content_type") or kind) if isinstance(meta, dict) else kind
    result["summary"] = "当前知识库证据不足，暂不输出确定性结论。"
    if content_type == "lecture":
        result["payload"] = {"sections": [{"heading": "证据状态", "content": "当前知识库不足以可靠生成该部分内容。"}]}
    elif content_type in {"practice", "practice_guide"}:
        result["payload"] = {
            "objectives": [],
            "steps": ["需补充资料后再执行。"],
            "checklist": [],
            "safety_points": ["不得基于未验证信息执行操作。"],
        }
    elif content_type in {"quiz", "question", "questions"}:
        result["payload"] = {"questions": []}
    elif content_type in {"qa", "qa_answer"}:
        payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
        payload["answer"] = "当前知识库未提供足够依据，暂不提供确定性结论。"
        result["payload"] = payload
    return result
