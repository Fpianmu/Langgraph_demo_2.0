from __future__ import annotations

import json
from typing import Any

from agent.node.node_logging import log_node_runtime
from agent.state import OverallState
from agent.tools.archive_tools import save_generated_artifact


@log_node_runtime("archive_writer_node")
def archive_writer_node(state: OverallState) -> OverallState:
    generated_content = state.get("generated_content") or state.get("final_output") or {}
    if not isinstance(generated_content, dict):
        generated_content = {}
    artifact_type = _artifact_type(state, generated_content)
    artifact = save_generated_artifact(
        user_id=str(state.get("user_id") or "default_user"),
        request_id=str(state.get("request_id") or ""),
        artifact_type=artifact_type,
        title=str(generated_content.get("title") or artifact_type),
        markdown_content=_markdown_for(generated_content),
        export_formats=_export_formats(state),
        metadata={
            "course_id": str(state.get("course_id") or ""),
            "chapter_id": str(state.get("chapter_id") or ""),
            "content_type": str(state.get("content_type") or artifact_type),
        },
        storage_root=state.get("_storage_root"),
    )
    return {
        "artifact_id": artifact["artifact_id"],
        "artifact_paths": {
            "markdown": artifact.get("markdown_path", ""),
            "docx": artifact.get("docx_path", ""),
            "pdf": artifact.get("pdf_path", ""),
        },
        "saved_artifact": artifact,
    }


def _artifact_type(state: OverallState, generated_content: dict[str, Any]) -> str:
    meta = generated_content.get("meta")
    if isinstance(meta, dict) and meta.get("content_type"):
        return str(meta["content_type"])
    content_type = str(state.get("content_type") or "artifact")
    return "practice_guide" if content_type == "practice" else content_type


def _export_formats(state: OverallState) -> list[str]:
    value = state.get("export_formats")
    if not isinstance(value, list):
        return []
    return [str(item).lower().lstrip(".") for item in value if str(item).strip()]


def _markdown_for(content: dict[str, Any]) -> str:
    title = str(content.get("title") or "Generated Artifact")
    summary = str(content.get("summary") or "")
    payload = content.get("payload") or {}
    lines = [f"# {title}", ""]
    if summary:
        lines.extend([summary, ""])
    if isinstance(payload, dict):
        lines.append("## Payload")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(payload, ensure_ascii=False, indent=2))
        lines.append("```")
    return "\n".join(lines).strip() + "\n"
