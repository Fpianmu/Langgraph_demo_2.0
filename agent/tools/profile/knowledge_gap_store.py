from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.storage_layout import safe_segment


class KnowledgeGapFileStore:
    def __init__(self, profile_dir: Path) -> None:
        self.profile_dir = profile_dir
        self.profile_dir.mkdir(parents=True, exist_ok=True)

    def sync(self, user_id: str, gaps: list[dict[str, Any]]) -> dict[str, Any]:
        folder = self.folder_for(user_id)
        folder.mkdir(parents=True, exist_ok=True)
        document = _document_for(user_id, gaps)
        self.json_path_for(user_id).write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
        self.markdown_path_for(user_id).write_text(_markdown_for(document), encoding="utf-8")
        self.events_path_for(user_id).touch()
        return {
            "files": self.file_refs_for(user_id),
            "summary": document["summary"],
        }

    def append_event(
        self,
        user_id: str,
        *,
        request_id: str,
        event_id: str,
        applied_knowledge_gaps: list[dict[str, Any]],
    ) -> dict[str, Any]:
        folder = self.folder_for(user_id)
        folder.mkdir(parents=True, exist_ok=True)
        event = {
            "event_id": event_id,
            "user_id": user_id,
            "request_id": request_id,
            "applied_knowledge_gaps": applied_knowledge_gaps,
            "created_at": _now(),
        }
        with self.events_path_for(user_id).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event

    def file_refs_for(self, user_id: str) -> dict[str, str]:
        return {
            "json": str(self.json_path_for(user_id)),
            "markdown": str(self.markdown_path_for(user_id)),
            "events": str(self.events_path_for(user_id)),
        }

    def folder_for(self, user_id: str) -> Path:
        return self.profile_dir / safe_segment(user_id) / "profile" / "knowledge_gaps"

    def json_path_for(self, user_id: str) -> Path:
        return self.folder_for(user_id) / "knowledge_gaps.json"

    def markdown_path_for(self, user_id: str) -> Path:
        return self.folder_for(user_id) / "knowledge_gaps.md"

    def events_path_for(self, user_id: str) -> Path:
        return self.folder_for(user_id) / "events.jsonl"


def _document_for(user_id: str, gaps: list[dict[str, Any]]) -> dict[str, Any]:
    normalized_gaps = [_normalize_gap(gap) for gap in gaps]
    summary = {
        "open_count": sum(1 for gap in normalized_gaps if gap["status"] == "open"),
        "high_count": sum(1 for gap in normalized_gaps if gap["severity"] == "high"),
        "medium_count": sum(1 for gap in normalized_gaps if gap["severity"] == "medium"),
        "low_count": sum(1 for gap in normalized_gaps if gap["severity"] == "low"),
        "resolved_count": sum(1 for gap in normalized_gaps if gap["status"] == "resolved"),
    }
    return {
        "user_id": user_id,
        "updated_at": _now(),
        "summary": summary,
        "gaps": normalized_gaps,
    }


def _normalize_gap(gap: dict[str, Any]) -> dict[str, Any]:
    evidence_items = _json_list(gap.get("evidence_items_json") or gap.get("evidence_items"))
    recommended_actions = _json_list(gap.get("recommended_actions_json") or gap.get("recommended_actions"))
    return {
        "gap_id": str(gap.get("gap_id") or ""),
        "knowledge_point_id": str(gap.get("knowledge_point_id") or ""),
        "concept": str(gap.get("concept") or ""),
        "chapter_id": str(gap.get("chapter_id") or ""),
        "category": str(gap.get("category") or ""),
        "severity": _severity(gap.get("severity")),
        "score": _score(gap.get("score")),
        "status": str(gap.get("status") or "open"),
        "source": str(gap.get("source") or ""),
        "evidence": str(gap.get("evidence") or ""),
        "evidence_items": [item for item in evidence_items if isinstance(item, dict)],
        "recommended_actions": [str(item) for item in recommended_actions if str(item).strip()],
        "updated_at": str(gap.get("updated_at") or ""),
    }


def _markdown_for(document: dict[str, Any]) -> str:
    gaps = document["gaps"]
    lines = [
        "# Knowledge Gap Summary",
        "",
        f"- User: {document['user_id']}",
        f"- Updated at: {document['updated_at']}",
        f"- Open gaps: {document['summary']['open_count']}",
        f"- High severity: {document['summary']['high_count']}",
        "",
    ]
    for severity in ("high", "medium", "low"):
        grouped = [gap for gap in gaps if gap["severity"] == severity]
        if not grouped:
            continue
        lines.extend([f"## {severity.title()} Priority", ""])
        for gap in grouped:
            lines.extend(
                [
                    f"### {gap['concept'] or gap['gap_id']}",
                    f"- Gap ID: {gap['gap_id']}",
                    f"- Knowledge point: {gap['knowledge_point_id']}",
                    f"- Chapter: {gap['chapter_id']}",
                    f"- Category: {gap['category']}",
                    f"- Severity: {gap['severity']}",
                    f"- Score: {gap['score']}",
                    f"- Status: {gap['status']}",
                    f"- Evidence: {gap['evidence']}",
                ]
            )
            if gap["recommended_actions"]:
                lines.append("- Recommended actions:")
                lines.extend(f"  - {action}" for action in gap["recommended_actions"])
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _severity(value: Any) -> str:
    text = str(value or "medium").strip()
    return text if text in {"low", "medium", "high"} else "medium"


def _score(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(max(parsed, 0.0), 1.0)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
