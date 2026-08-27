from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    source_file: str
    chunk_id: str
    text: str
    score: float = 0.0
    file_type: str | None = None
    page_label: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Citation(BaseModel):
    source_file: str
    chunk_id: str
    label: str


class RagPackage(BaseModel):
    query: str
    answer: str
    evidence: list[EvidenceItem] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = 0.0
    warnings: list[str] = Field(default_factory=list)
    next_action: Literal["use_as_grounded_context", "need_more_evidence"] = "need_more_evidence"

