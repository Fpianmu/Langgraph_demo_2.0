from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.tools.learning_archive.manager import LearningArchiveManager


def save_generated_artifact(
    *,
    user_id: str,
    request_id: str,
    artifact_type: str,
    title: str,
    markdown_content: str,
    export_formats: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    storage_root: str | Path | None = None,
) -> dict[str, Any]:
    return LearningArchiveManager(storage_root).save_generated_artifact(
        user_id=user_id,
        request_id=request_id,
        artifact_type=artifact_type,
        title=title,
        markdown_content=markdown_content,
        export_formats=export_formats,
        metadata=metadata,
    )


def save_question_set_json(
    *,
    user_id: str,
    request_id: str,
    title: str,
    questions: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
    storage_root: str | Path | None = None,
) -> dict[str, Any]:
    return LearningArchiveManager(storage_root).save_question_set_json(
        user_id=user_id,
        request_id=request_id,
        title=title,
        questions=questions,
        metadata=metadata,
    )
