from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.storage_layout import safe_segment


class PathAssignmentFileStore:
    def __init__(self, profile_dir: Path) -> None:
        self.profile_dir = profile_dir
        self.profile_dir.mkdir(parents=True, exist_ok=True)

    def sync(self, user_id: str, assignments: list[dict[str, Any]]) -> dict[str, Any]:
        path = self.path_for(user_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "schema_version": "1.0",
            "user_id": user_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "assignments": {
                str(item["course_id"]): _normalized_assignment(item)
                for item in assignments
                if str(item.get("course_id") or "").strip()
            },
        }
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"files": self.file_refs_for(user_id), "document": document}

    def file_refs_for(self, user_id: str) -> dict[str, str]:
        return {"json": str(self.path_for(user_id))}

    def path_for(self, user_id: str) -> Path:
        return self.profile_dir / safe_segment(user_id) / "profile" / "path_assignments.json"


def _normalized_assignment(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "course_id": str(item.get("course_id") or ""),
        "learner_level": str(item.get("learner_level") or ""),
        "path_id": str(item.get("path_id") or ""),
        "path_version": str(item.get("path_version") or ""),
        "classification_source": str(item.get("classification_source") or ""),
        "classification_score": item.get("classification_score"),
        "classification_reason": str(item.get("classification_reason") or ""),
        "manual_override": bool(item.get("manual_override")),
        "assigned_at": str(item.get("assigned_at") or ""),
        "updated_at": str(item.get("updated_at") or ""),
    }
