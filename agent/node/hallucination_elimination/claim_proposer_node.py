from __future__ import annotations

import json
from typing import Any

from agent.node.node_logging import log_node_runtime
from agent.node.verification_utils import get_review_materials, human_message, json_loads_object
from agent.rag.config import RagConfig
from agent.state import OverallState


_verification_model: Any | None = None


@log_node_runtime("claim_proposer_node")
def claim_proposer_node(state: OverallState) -> OverallState:
    materials = get_review_materials(state)
    claims: list[dict[str, Any]] = []
    raw_outputs: dict[str, str] = {}
    for material_type, material in materials.items():
        raw = _invoke_model(state, _build_prompt(material_type, material))
        raw_outputs[material_type] = raw
        data = json_loads_object(raw)
        for item in data.get("claims") if isinstance(data.get("claims"), list) else []:
            if isinstance(item, dict):
                claim = _normalize_claim(item, material_type, len(claims) + 1)
                if claim["claim_text"]:
                    claims.append(claim)
    return {
        "verification_claims": claims,
        "verification_summary": {"claim_count": len(claims)},
        "verification_history": [
            *(state.get("verification_history") or []),
            {"node": "claim_proposer_node", "claim_count": len(claims)},
        ],
        "claim_proposer_raw_outputs": raw_outputs,
    }


def _build_prompt(material_type: str, material: dict[str, Any]) -> str:
    return f"""
你是 Claim Proposer。你的任务仅是拆分可核验专业事实，不做真假判断。
输入包含 material_type 与 material JSON。

要求：
1. 每条 claim 必须是最小、独立、可判断真假的事实单元；
2. 不新增原材料中不存在的信息；
3. field_path 使用 JSON Pointer，必须指向原材料真实字段；
4. 设备参数、安全阈值、危险动作、操作权限标记 risk_level=high；
5. 不拆 title、learning_guidance、next_actions、follow_ups、meta；
6. 只返回 JSON：{{"claims": [...]}}。

material_type:
{material_type}

material_json:
{json.dumps(material, ensure_ascii=False)}
""".strip()


def _normalize_claim(item: dict[str, Any], material_type: str, index: int) -> dict[str, Any]:
    claim_type = str(item.get("claim_type") or "factual").strip()
    if claim_type not in {"factual", "numeric", "causal", "procedural", "safety", "answer_key"}:
        claim_type = "factual"
    risk = str(item.get("risk_level") or "medium").strip().lower()
    if risk not in {"low", "medium", "high"}:
        risk = "medium"
    text = str(
        item.get("claim_text")
        or item.get("text")
        or item.get("statement")
        or item.get("claim")
        or item.get("content")
        or ""
    ).strip()
    if _looks_high_risk(text, claim_type):
        risk = "high"
    return {
        "claim_id": str(item.get("claim_id") or f"{material_type}_{index:04d}"),
        "material_type": str(item.get("material_type") or material_type),
        "field_path": str(item.get("field_path") or ""),
        "claim_text": text,
        "claim_type": claim_type,
        "risk_level": risk,
    }


def _looks_high_risk(text: str, claim_type: str) -> bool:
    if claim_type in {"numeric", "procedural", "safety"}:
        return True
    markers = ("转速", "进给", "切削深度", "阈值", "危险", "运行中", "不停机", "权限", "安全")
    return any(marker in text for marker in markers)


def _invoke_model(state: OverallState, prompt: str) -> str:
    model = state.get("_verification_model") or state.get("_generation_model") or state.get("_model") or _default_model()
    response = model.invoke([human_message(prompt)])
    return str(response.content)


def _default_model() -> Any:
    global _verification_model
    if _verification_model is None:
        from langchain_deepseek import ChatDeepSeek

        _verification_model = ChatDeepSeek(
            model=RagConfig.from_env().deepseek_model,
            extra_body={"thinking": {"type": "disabled"}},
        )
    return _verification_model
