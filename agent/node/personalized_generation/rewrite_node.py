from __future__ import annotations

import json
from typing import Any

from agent.node.node_logging import log_node_runtime
from agent.node.verification_utils import (
    apply_allowed_patches,
    collect_evidence,
    evidence_prompt_text,
    get_review_materials,
    human_message,
    json_loads_object,
    write_review_materials,
)
from agent.rag.config import RagConfig
from agent.state import OverallState


_rewrite_model: Any | None = None


@log_node_runtime("rewrite_node")
def rewrite_node(state: OverallState) -> OverallState:
    materials = get_review_materials(state)
    failed_checks = [item for item in (state.get("claim_checks") or []) if item.get("label") in {"partial", "unsupported", "conflict"}]
    claims = [item for item in (state.get("verification_claims") or []) if isinstance(item, dict)]
    evidence = collect_evidence(state)
    rewritten: dict[str, dict[str, Any]] = {}
    raw_outputs: dict[str, str] = {}
    for material_type, material in materials.items():
        related_claims = [claim for claim in claims if claim.get("material_type") in {material_type, "single"}]
        related_checks = [check for check in failed_checks if check.get("claim_id") in {claim.get("claim_id") for claim in related_claims}]
        if not related_checks:
            rewritten[material_type] = material
            continue
        raw = _invoke_model(state, _build_prompt(material_type, material, related_claims, related_checks, evidence))
        raw_outputs[material_type] = raw
        data = json_loads_object(raw)
        patches = data.get("patches") if isinstance(data.get("patches"), list) else []
        rewritten[material_type] = apply_allowed_patches(material, [item for item in patches if isinstance(item, dict)], material_type)
    update = write_review_materials(state, rewritten)
    update["verification_rewrite_count"] = int(state.get("verification_rewrite_count") or 0) + 1
    update["rewrite_raw_outputs"] = raw_outputs
    return update


def _build_prompt(
    material_type: str,
    material: dict[str, Any],
    claims: list[dict[str, Any]],
    checks: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> str:
    return f"""
你是反幻觉回修节点。只能基于 failed claims、checks 与 evidence 生成 JSON Patch。
要求：
1. 只返回 replace 操作；
2. unsupported 仍缺证据时，替换为“当前资料未充分覆盖/需补充资料”，不得补写新事实；
3. conflict 用 evidence 支持的表述替换；
4. partial 只删除或弱化超出 evidence 的部分；
5. 不修改 meta、evidence_refs、验证记录。
只返回 JSON：{{"patches": [{{"op":"replace","path":"...","value":"..."}}]}}。

material_type:
{material_type}

material:
{json.dumps(material, ensure_ascii=False)}

claims:
{json.dumps(claims, ensure_ascii=False)}

checks:
{json.dumps(checks, ensure_ascii=False)}

evidence:
{evidence_prompt_text(evidence)}
""".strip()


def _invoke_model(state: OverallState, prompt: str) -> str:
    model = state.get("_verification_model") or state.get("_generation_model") or state.get("_model") or _default_model()
    response = model.invoke([human_message(prompt)])
    return str(response.content)


def _default_model() -> Any:
    global _rewrite_model
    if _rewrite_model is None:
        from langchain_deepseek import ChatDeepSeek

        _rewrite_model = ChatDeepSeek(
            model=RagConfig.from_env().deepseek_model,
            extra_body={"thinking": {"type": "disabled"}},
        )
    return _rewrite_model
