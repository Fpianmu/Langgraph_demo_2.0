from __future__ import annotations

import json
from typing import Any

from agent.node.node_logging import log_node_runtime
from agent.node.verification_utils import human_message, json_loads_object
from agent.rag.config import RagConfig
from agent.state import OverallState


_query_model: Any | None = None


@log_node_runtime("verification_query_planner_node")
def verification_query_planner_node(state: OverallState) -> OverallState:
    failed = [item for item in (state.get("claim_checks") or []) if item.get("label") in {"unsupported", "partial"}]
    if not failed:
        return {"verification_queries": state.get("verification_queries") or []}
    raw = _invoke_model(state, _build_prompt(state.get("verification_claims") or [], failed))
    data = json_loads_object(raw)
    queries = data.get("verification_queries") if isinstance(data.get("verification_queries"), list) else []
    clean = []
    seen = set()
    for query in [*queries, *(state.get("verification_queries") or [])]:
        text = str(query).strip()
        if text and text not in seen:
            clean.append(text)
            seen.add(text)
    return {"verification_queries": clean, "verification_query_planner_raw_output": raw}


def _build_prompt(claims: list[dict[str, Any]], failed_checks: list[dict[str, Any]]) -> str:
    return f"""
你是 Verification Query Planner。根据失败 claim 生成短检索查询。
只返回 JSON：{{"verification_queries": ["query"]}}。

claims:
{json.dumps(claims, ensure_ascii=False)}

failed_checks:
{json.dumps(failed_checks, ensure_ascii=False)}
""".strip()


def _invoke_model(state: OverallState, prompt: str) -> str:
    model = state.get("_verification_model") or state.get("_generation_model") or state.get("_model") or _default_model()
    response = model.invoke([human_message(prompt)])
    return str(response.content)


def _default_model() -> Any:
    global _query_model
    if _query_model is None:
        from langchain_deepseek import ChatDeepSeek

        _query_model = ChatDeepSeek(
            model=RagConfig.from_env().deepseek_model,
            extra_body={"thinking": {"type": "disabled"}},
        )
    return _query_model
