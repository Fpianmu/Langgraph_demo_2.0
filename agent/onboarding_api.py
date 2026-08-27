from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

from agent.onboarding import (
    assessment_result_for,
    create_onboarding_assessment,
    registered_users,
    register_onboarding_user,
    submit_onboarding_assessment,
)


def register_onboarding_routes(app: FastAPI, *, storage_root: str | Path | None = None) -> None:
    @app.post("/api/onboarding/assessments")
    def create_assessment_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
        return create_onboarding_assessment(
            course_id=str(payload.get("course_id") or "cnc_lathe"),
        )

    @app.post("/api/onboarding/assessments/{assessment_id}/submit")
    def submit_assessment_endpoint(assessment_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        answers = payload.get("answers")
        if not isinstance(answers, list):
            raise HTTPException(status_code=400, detail="answers must be a list")
        try:
            return submit_onboarding_assessment(
                assessment_id=assessment_id,
                answers=[item for item in answers if isinstance(item, dict)],
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="assessment not found") from None

    @app.post("/api/users")
    def create_user_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
        user_id = str(payload.get("user_id") or "").strip()
        if not user_id:
            raise HTTPException(status_code=400, detail="user_id is required")

        assessment_result = payload.get("assessment_result")
        if not isinstance(assessment_result, dict):
            assessment_id = str(payload.get("assessment_id") or "").strip()
            assessment_result = assessment_result_for(assessment_id) if assessment_id else None
        if not isinstance(assessment_result, dict):
            raise HTTPException(status_code=400, detail="scored onboarding assessment is required")

        try:
            return register_onboarding_user(
                user_id=user_id,
                display_name=_optional_text(payload.get("display_name")),
                background_type=_optional_text(payload.get("background_type")),
                assessment_result=assessment_result,
                storage_root=storage_root,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @app.get("/api/users")
    def list_users_endpoint() -> dict[str, Any]:
        return {"users": registered_users(storage_root=storage_root)}


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
