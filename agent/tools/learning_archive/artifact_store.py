from __future__ import annotations

from pathlib import Path

from agent.storage_layout import safe_segment, user_root


class ArtifactStore:
    def __init__(self, storage_root: Path) -> None:
        self.storage_root = storage_root
        self.storage_root.mkdir(parents=True, exist_ok=True)

    def write_markdown(self, *, user_id: str, artifact_type: str, artifact_id: str, content: str) -> Path:
        path = self.path_for(user_id=user_id, artifact_type=artifact_type, artifact_id=artifact_id, suffix=".md")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def path_for(self, *, user_id: str, artifact_type: str, artifact_id: str, suffix: str) -> Path:
        folder = self.folder_for(user_id=user_id, artifact_type=artifact_type, artifact_id=artifact_id)
        return folder / f"{_stem_for(artifact_type)}{suffix}"

    def folder_for(self, *, user_id: str, artifact_type: str, artifact_id: str) -> Path:
        return user_root(self.storage_root, user_id) / _folder_for(artifact_type) / safe_segment(artifact_id)


def _folder_for(artifact_type: str) -> str:
    mapping = {
        "quiz": "questions/custom_generated",
        "lecture": "lectures",
        "practice_guide": "practice_outputs",
        "practice": "practice_outputs",
        "qa_answer": "conversations",
    }
    if artifact_type == "qa_answer":
        return "conversations"
    return mapping.get(artifact_type, "misc")


def _stem_for(artifact_type: str) -> str:
    mapping = {
        "quiz": "questions",
        "lecture": "lecture",
        "practice_guide": "practice",
        "practice": "practice",
        "qa_answer": "transcript",
    }
    return mapping.get(artifact_type, "artifact")
