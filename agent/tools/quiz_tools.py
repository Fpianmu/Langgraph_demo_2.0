from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.tools.learning_archive.manager import LearningArchiveManager


def save_quiz_items(
    *,
    artifact_id: str,
    user_id: str,
    items: list[dict[str, Any]],
    storage_root: str | Path | None = None,
) -> dict[str, Any]:
    return LearningArchiveManager(storage_root).save_quiz_items(
        artifact_id=artifact_id,
        user_id=user_id,
        items=items,
    )


def save_quiz_attempt(
    *,
    user_id: str,
    artifact_id: str,
    answers: list[dict[str, Any]],
    storage_root: str | Path | None = None,
) -> dict[str, Any]:
    return LearningArchiveManager(storage_root).save_quiz_attempt(
        user_id=user_id,
        artifact_id=artifact_id,
        answers=answers,
    )


def save_operation_submission_review(
    *,
    user_id: str,
    course_id: str,
    chapter_id: str,
    task_id: str,
    workpiece_id: str,
    measurement_params: dict[str, Any],
    uploaded_images: list[dict[str, Any]] | None = None,
    vl_analysis_result: dict[str, Any] | None = None,
    measurement_comparison_result: dict[str, Any] | None = None,
    operation_review_result: dict[str, Any] | None = None,
    llm_review_report: str = "",
    request_id: str = "",
    storage_root: str | Path | None = None,
) -> dict[str, Any]:
    return LearningArchiveManager(storage_root).save_operation_submission_review(
        user_id=user_id,
        course_id=course_id,
        chapter_id=chapter_id,
        task_id=task_id,
        workpiece_id=workpiece_id,
        measurement_params=measurement_params,
        uploaded_images=uploaded_images,
        vl_analysis_result=vl_analysis_result,
        measurement_comparison_result=measurement_comparison_result,
        operation_review_result=operation_review_result,
        llm_review_report=llm_review_report,
        request_id=request_id,
    )
