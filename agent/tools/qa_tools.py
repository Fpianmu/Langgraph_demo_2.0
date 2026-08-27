from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.tools.learning_archive.manager import LearningArchiveManager


def create_qa_session(
    *,
    user_id: str,
    course_id: str,
    title: str,
    storage_root: str | Path | None = None,
) -> dict[str, Any]:
    return LearningArchiveManager(storage_root).create_qa_session(
        user_id=user_id,
        course_id=course_id,
        title=title,
    )


def save_qa_message(
    *,
    session_id: str,
    user_id: str,
    role: str,
    content: str,
    related_artifact_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    storage_root: str | Path | None = None,
) -> dict[str, Any]:
    return LearningArchiveManager(storage_root).save_qa_message(
        session_id=session_id,
        user_id=user_id,
        role=role,
        content=content,
        related_artifact_id=related_artifact_id,
        metadata=metadata,
    )


def load_qa_session_context(
    *,
    user_id: str,
    session_id: str,
    max_messages: int = 20,
    storage_root: str | Path | None = None,
) -> dict[str, Any]:
    return LearningArchiveManager(storage_root).load_qa_session_context(
        user_id=user_id,
        session_id=session_id,
        max_messages=max_messages,
    )
