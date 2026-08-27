from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.tools.profile.capability_assessment_store import CapabilityAssessmentDbStore
from agent.tools.profile.config import ProfileConfig
from agent.tools.profile.knowledge_gap_store import KnowledgeGapFileStore
from agent.tools.profile.markdown_store import ProfileMarkdownStore
from agent.tools.profile.path_assignment_store import PathAssignmentFileStore
from agent.tools.profile.repository import ProfileRepository
from agent.storage_layout import migrate_legacy_storage


class ProfileManager:
    def __init__(self, storage_root: str | Path | None = None) -> None:
        self.config = ProfileConfig.from_root(storage_root)
        migrate_legacy_storage(self.config.storage_root)
        self.repository = ProfileRepository(self.config.db_path)
        self.markdown_store = ProfileMarkdownStore(self.config.profile_dir)
        self.capability_assessment_store = CapabilityAssessmentDbStore(self.config.db_path)
        self.knowledge_gap_store = KnowledgeGapFileStore(self.config.profile_dir)
        self.path_assignment_store = PathAssignmentFileStore(self.config.profile_dir)

    def load_profile_context(
        self,
        user_id: str,
        *,
        display_name: str | None = None,
        background_type: str | None = None,
    ) -> dict[str, Any]:
        user = self.repository.get_or_create_user(
            user_id,
            display_name=display_name,
            background_type=background_type,
        )
        markdown = self.markdown_store.get_or_create(
            user_id,
            display_name=user.get("display_name"),
            background_type=user.get("background_type"),
        )
        capability_assessment_sync = self.capability_assessment_store.sync(user_id)
        knowledge_gaps = self.repository.list_knowledge_gaps(user_id)
        knowledge_gap_sync = self.knowledge_gap_store.sync(user_id, knowledge_gaps)
        path_assignments = self.repository.list_path_assignments(user_id)
        path_assignment_sync = self.path_assignment_store.sync(user_id, path_assignments)
        return {
            "user_id": user_id,
            "user": user,
            "metrics": self.repository.get_metrics(user_id),
            "capability_assessment": capability_assessment_sync["document"],
            "capability_profile_score": capability_assessment_sync["profile_score"],
            "capability_assessment_files": capability_assessment_sync["files"],
            "capability_assessment_summary": capability_assessment_sync["summary"],
            "knowledge_gaps": knowledge_gaps,
            "knowledge_gap_files": knowledge_gap_sync["files"],
            "knowledge_gap_summary": knowledge_gap_sync["summary"],
            "learning_progress": self.repository.list_learning_progress(user_id),
            "path_assignments": path_assignments,
            "path_assignment_files": path_assignment_sync["files"],
            "profile_md_ref": str(self.markdown_store.path_for(user_id)),
            "profile_md_content": markdown,
        }

    def assign_learning_path(self, user_id: str, assignment: dict[str, Any]) -> dict[str, Any]:
        self.repository.get_or_create_user(user_id)
        persisted = self.repository.upsert_path_assignment(user_id, assignment)
        assignments = self.repository.list_path_assignments(user_id)
        self.path_assignment_store.sync(user_id, assignments)
        self.markdown_store.upsert_section(
            user_id,
            "学习路径分配",
            _path_assignment_markdown(assignments),
        )
        return persisted

    def apply_update_suggestions(self, user_id: str, request_id: str, suggestions: dict[str, Any]) -> dict[str, Any]:
        self.repository.get_or_create_user(user_id)
        metric_patches = _list_of_dicts(suggestions.get("metric_patches"))
        capability_evidence = _list_of_dicts(suggestions.get("capability_evidence"))
        gap_patches = _list_of_dicts(suggestions.get("knowledge_gap_patches"))
        progress_patches = _list_of_dicts(suggestions.get("progress_patches"))

        applied_metrics = self.repository.update_metrics(user_id, metric_patches)
        capability_sync = self.capability_assessment_store.append_evidence(user_id, capability_evidence)
        applied_gaps = self.repository.upsert_knowledge_gaps(user_id, gap_patches)
        applied_progress = self.repository.upsert_learning_progress(user_id, progress_patches)

        markdown_patch = suggestions.get("markdown_patch")
        markdown_updated = False
        if isinstance(markdown_patch, dict):
            section = str(markdown_patch.get("section") or "").strip()
            content = str(markdown_patch.get("content") or "").strip()
            if section and content:
                self.markdown_store.apply_section_patch(user_id, section, content)
                markdown_updated = True

        event_id = self.repository.record_update_event(
            user_id,
            request_id,
            suggestions,
            accepted=True,
            reason="validated_by_profile_manager",
        )
        knowledge_gap_sync = self.knowledge_gap_store.sync(
            user_id,
            self.repository.list_knowledge_gaps(user_id),
        )
        self.knowledge_gap_store.append_event(
            user_id,
            request_id=request_id,
            event_id=event_id,
            applied_knowledge_gaps=applied_gaps,
        )
        return {
            "accepted": True,
            "event_id": event_id,
            "applied_metrics": applied_metrics,
            "applied_capability_evidence": capability_sync["applied_evidence"],
            "applied_capability_evidence_count": len(capability_sync["applied_evidence"]),
            "capability_profile_score": capability_sync["profile_score"],
            "capability_assessment_files": capability_sync["files"],
            "capability_assessment_summary": capability_sync["summary"],
            "applied_knowledge_gaps": applied_gaps,
            "applied_learning_progress": applied_progress,
            "markdown_updated": markdown_updated,
            "knowledge_gap_files": knowledge_gap_sync["files"],
            "knowledge_gap_summary": knowledge_gap_sync["summary"],
        }

    def list_users(self) -> list[dict[str, Any]]:
        return self.repository.list_users()

    def record_resource_difficulty(
        self,
        user_id: str,
        record: dict[str, Any],
    ) -> dict[str, Any]:
        self.repository.get_or_create_user(user_id)
        return self.repository.append_resource_difficulty_record(user_id, record)

    def load_resource_difficulty_trace(self, user_id: str, *, limit: int = 200) -> dict[str, Any]:
        context = self.load_profile_context(user_id)
        records = self.repository.list_resource_difficulty_records(user_id, limit=limit)
        return {
            "user_id": user_id,
            "capability_profile_score": context.get("capability_profile_score", {}),
            "resource_difficulty_records": records,
            "record_count": len(records),
        }


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _path_assignment_markdown(assignments: list[dict[str, Any]]) -> str:
    level_labels = {"beginner": "基础", "standard": "标准", "advanced": "进阶"}
    lines = []
    for item in assignments:
        level = str(item.get("learner_level") or "")
        label = level_labels.get(level, level or "未分类")
        lines.append(f"- {item['course_id']}: {item['path_id']}（{label}）")
        source = str(item.get("classification_source") or "")
        if source:
            lines.append(f"  - 分配来源: {source}")
        reason = str(item.get("classification_reason") or "")
        if reason:
            lines.append(f"  - 分配依据: {reason}")
    return "\n".join(lines) if lines else "暂无。"
