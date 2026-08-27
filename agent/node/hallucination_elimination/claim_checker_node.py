from __future__ import annotations

import json
from typing import Any

from agent.node.node_logging import log_node_runtime
from agent.node.verification_utils import collect_evidence, evidence_prompt_text, human_message, json_loads_object
from agent.rag.config import RagConfig
from agent.state import OverallState


_checker_model: Any | None = None


@log_node_runtime("claim_checker_node")
def claim_checker_node(state: OverallState) -> OverallState:
    claims = [item for item in (state.get("verification_claims") or []) if isinstance(item, dict)]
    if not claims:
        return {
            "claim_checks": [],
            "verification_queries": [],
            "verification_summary": _summary([]),
        }
    selected = state.get("selected_verification_evidence")
    evidence = [item for item in selected if isinstance(item, dict)] if isinstance(selected, list) else collect_evidence(state)
    raw = _invoke_model(state, _build_prompt(claims, evidence))
    data = json_loads_object(raw)
    checks = [_normalize_check(item) for item in data.get("checks") if isinstance(item, dict)] if isinstance(data.get("checks"), list) else []
    if len(checks) != len(claims):
        checks = _fallback_unsupported_checks(claims)
    queries = _queries_from_checks(checks)
    return {
        "claim_checks": checks,
        "verification_queries": queries,
        "verification_summary": _summary(checks),
        "claim_checker_raw_output": raw,
        "verification_history": [
            *(state.get("verification_history") or []),
            {"node": "claim_checker_node", "summary": _summary(checks)},
        ],
    }


def _build_prompt(claims: list[dict[str, Any]], evidence: list[dict[str, Any]]) -> str:
    return f"""
你是独立事实核验 Agent。只能依据 evidence 判断 claims。
禁止使用你自己的常识、训练知识或推测认定 claim 为 supported。
没有证据时必须标记 unsupported；证据只覆盖部分时标记 partial；与证据矛盾时标记 conflict。
每个 supported/partial/conflict 必须给 evidence_refs；unsupported 必须给 retrieval_query。
只返回 JSON：{{"checks": [...]}}。

claims:
{json.dumps(claims, ensure_ascii=False)}

evidence:
{evidence_prompt_text(evidence)}
""".strip()


def _normalize_check(item: dict[str, Any]) -> dict[str, Any]:
    label = str(item.get("label") or item.get("status") or item.get("verdict") or "unsupported").strip()
    if label not in {"supported", "partial", "unsupported", "conflict"}:
        label = "unsupported"
    evidence_refs = item.get("evidence_refs") if isinstance(item.get("evidence_refs"), list) else []
    return {
        "claim_id": str(item.get("claim_id") or ""),
        "label": label,
        "confidence": _confidence(item.get("confidence")),
        "evidence_refs": _normalize_evidence_refs(evidence_refs),
        "reason": str(item.get("reason") or ""),
        "retrieval_query": str(item.get("retrieval_query") or ""),
    }


def _normalize_evidence_refs(value: list[Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for ref in value:
        if isinstance(ref, dict):
            refs.append(ref)
        elif isinstance(ref, str) and ref.strip():
            refs.append({"chunk_id": ref.strip()})
    return refs


def _fallback_unsupported_checks(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "claim_id": str(claim.get("claim_id") or ""),
            "label": "unsupported",
            "confidence": 0.0,
            "evidence_refs": [],
            "reason": "Checker did not return a complete check list.",
            "retrieval_query": str(claim.get("claim_text") or ""),
        }
        for claim in claims
    ]


def _queries_from_checks(checks: list[dict[str, Any]]) -> list[str]:
    queries = []
    seen = set()
    for check in checks:
        if check.get("label") != "unsupported":
            continue
        query = str(check.get("retrieval_query") or "").strip()
        if query and query not in seen:
            queries.append(query)
            seen.add(query)
    return queries


def _summary(checks: list[dict[str, Any]]) -> dict[str, Any]:
    labels = [str(item.get("label") or "") for item in checks]
    return {
        "total": len(checks),
        "supported": labels.count("supported"),
        "partial": labels.count("partial"),
        "unsupported": labels.count("unsupported"),
        "conflict": labels.count("conflict"),
        "high_risk_failed": 0,
    }


def _confidence(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(max(parsed, 0.0), 1.0)


def _invoke_model(state: OverallState, prompt: str) -> str:
    model = state.get("_verification_model") or state.get("_generation_model") or state.get("_model") or _default_model()
    response = model.invoke([human_message(prompt)])
    return str(response.content)


def _default_model() -> Any:
    global _checker_model
    if _checker_model is None:
        from langchain_deepseek import ChatDeepSeek

        _checker_model = ChatDeepSeek(
            model=RagConfig.from_env().deepseek_model,
            extra_body={"thinking": {"type": "disabled"}},
        )
    return _checker_model
