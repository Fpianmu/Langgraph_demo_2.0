from __future__ import annotations

import json
from typing import Any

from agent.node.node_logging import log_node_runtime
from agent.node.verification_utils import collect_evidence, evidence_prompt_text, human_message, json_loads_object
from agent.rag.config import RagConfig
from agent.state import OverallState


_selector_model: Any | None = None


@log_node_runtime("evidence_selector_node")
def evidence_selector_node(state: OverallState) -> OverallState:
    claims = [item for item in (state.get("verification_claims") or []) if isinstance(item, dict)]
    evidence = collect_evidence(state)
    if not claims or not evidence:
        return {"claim_evidence_map": {}, "selected_verification_evidence": evidence}
    raw = _invoke_model(state, _build_prompt(claims, evidence))
    data = json_loads_object(raw)
    mapping = data.get("claim_evidence_map") if isinstance(data.get("claim_evidence_map"), dict) else {}
    selected_ids = {str(chunk_id) for ids in mapping.values() if isinstance(ids, list) for chunk_id in ids}
    selected = [item for item in evidence if str(item.get("chunk_id")) in selected_ids]
    return {
        "claim_evidence_map": mapping,
        "selected_verification_evidence": selected or evidence[:12],
        "evidence_selector_raw_output": raw,
    }


def _build_prompt(claims: list[dict[str, Any]], evidence: list[dict[str, Any]]) -> str:
    return f"""
你是 Evidence Selector。为每条 claim 选择最相关的 evidence chunk_id。
只返回 JSON：{{"claim_evidence_map": {{"claim_id": ["chunk_id"]}}}}。

claims:
{json.dumps(claims, ensure_ascii=False)}

evidence:
{evidence_prompt_text(evidence, limit=20)}
""".strip()


def _invoke_model(state: OverallState, prompt: str) -> str:
    model = state.get("_verification_model") or state.get("_generation_model") or state.get("_model") or _default_model()
    response = model.invoke([human_message(prompt)])
    return str(response.content)


def _default_model() -> Any:
    global _selector_model
    if _selector_model is None:
        from langchain_deepseek import ChatDeepSeek

        _selector_model = ChatDeepSeek(
            model=RagConfig.from_env().deepseek_model,
            extra_body={"thinking": {"type": "disabled"}},
        )
    return _selector_model
