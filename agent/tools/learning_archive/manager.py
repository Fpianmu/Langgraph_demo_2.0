from __future__ import annotations

import json
import base64
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent.tools.learning_archive.artifact_store import ArtifactStore
from agent.tools.learning_archive.config import ArchiveConfig
from agent.tools.learning_archive.repository import ArchiveRepository
from agent.storage_layout import migrate_legacy_storage, safe_segment, user_root


class LearningArchiveManager:
    def __init__(self, storage_root: str | Path | None = None) -> None:
        self.config = ArchiveConfig.from_root(storage_root)
        migrate_legacy_storage(self.config.storage_root)
        self.repository = ArchiveRepository(self.config.db_path)
        self.artifact_store = ArtifactStore(self.config.artifact_dir)

    def save_generated_artifact(
        self,
        *,
        user_id: str,
        request_id: str,
        artifact_type: str,
        title: str,
        markdown_content: str,
        export_formats: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        source_node: str = "agent_tool",
    ) -> dict[str, Any]:
        metadata = metadata or {}
        if artifact_type in {"quiz", "question", "questions"}:
            source = metadata.get("source")
            questions = source.get("questions") if isinstance(source, dict) else []
            return self.save_question_set_json(
                user_id=user_id,
                request_id=request_id,
                title=title,
                questions=[item for item in questions if isinstance(item, dict)] if isinstance(questions, list) else [],
                metadata=metadata,
                source_node=source_node,
            )
        artifact_id = f"{artifact_type}_{uuid4().hex[:12]}"
        markdown_path = self.artifact_store.write_markdown(
            user_id=user_id,
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            content=markdown_content,
        )
        markdown_assets = self._copy_markdown_assets(
            markdown_path.parent,
            markdown_content,
            metadata.get("markdown_asset_roots"),
        )
        exported: dict[str, Path] = {}
        row = {
            "artifact_id": artifact_id,
            "user_id": user_id,
            "request_id": request_id,
            "artifact_type": artifact_type,
            "title": title,
            "course_id": str(metadata.get("course_id") or ""),
            "chapter_id": str(metadata.get("chapter_id") or ""),
            "source_node": source_node,
            "markdown_path": self._relative(markdown_path),
            "docx_path": self._relative(exported["docx"]) if "docx" in exported else "",
            "pdf_path": self._relative(exported["pdf"]) if "pdf" in exported else "",
            "markdown_assets": markdown_assets,
            "metadata_json": json.dumps(metadata, ensure_ascii=False),
        }
        manifest_path = markdown_path.parent / "manifest.json"
        manifest_path.write_text(
            json.dumps(_manifest_for(row, exported=exported), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.repository.insert_artifact(row)
        return row

    def save_question_set_json(
        self,
        *,
        user_id: str,
        request_id: str,
        title: str,
        questions: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
        source_node: str = "agent_tool",
    ) -> dict[str, Any]:
        artifact_type = "quiz"
        artifact_id = f"{artifact_type}_{uuid4().hex[:12]}"
        metadata = metadata or {}
        folder = self._question_artifact_folder(user_id=user_id, artifact_id=artifact_id, metadata=metadata)
        folder.mkdir(parents=True, exist_ok=True)
        questions_path = folder / "questions.json"
        questions_path.write_text(
            json.dumps(
                {
                    "question_set_id": artifact_id,
                    "artifact_id": artifact_id,
                    "user_id": user_id,
                    "course_id": str(metadata.get("course_id") or ""),
                    "chapter_id": str(metadata.get("chapter_id") or ""),
                    "title": title,
                    "items": questions,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        row = {
            "artifact_id": artifact_id,
            "user_id": user_id,
            "request_id": request_id,
            "artifact_type": artifact_type,
            "title": title,
            "course_id": str(metadata.get("course_id") or ""),
            "chapter_id": str(metadata.get("chapter_id") or ""),
            "source_node": source_node,
            "markdown_path": "",
            "docx_path": "",
            "pdf_path": "",
            "metadata_json": json.dumps(metadata, ensure_ascii=False),
        }
        manifest = {
            "artifact_id": artifact_id,
            "user_id": user_id,
            "title": title,
            "course_id": row["course_id"],
            "chapter_id": row["chapter_id"],
            "artifact_type": artifact_type,
            "question_scope": _question_scope(metadata),
            "chapter_group": _chapter_group(row["chapter_id"]),
            "source_node": source_node,
            "files": {"questions": self._relative(questions_path)},
        }
        (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        self.repository.insert_artifact(row)
        normalized_items = [_quiz_item_from_question(question) for question in questions]
        item_ids = self.repository.insert_quiz_items(artifact_id, user_id, normalized_items)
        return {
            **row,
            "questions_path": self._relative(questions_path),
            "item_ids": item_ids,
            "item_count": len(item_ids),
        }

    def save_quiz_items(self, *, artifact_id: str, user_id: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        item_ids = self.repository.insert_quiz_items(artifact_id, user_id, items)
        folder = self._question_artifact_folder_for_existing(user_id=user_id, artifact_id=artifact_id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "questions.json").write_text(
            json.dumps({"artifact_id": artifact_id, "user_id": user_id, "items": items}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {"artifact_id": artifact_id, "item_ids": item_ids, "item_count": len(item_ids)}

    def save_quiz_attempt(self, *, user_id: str, artifact_id: str, answers: list[dict[str, Any]]) -> dict[str, Any]:
        result = self.repository.insert_quiz_attempt(user_id, artifact_id, answers)
        result["artifact_id"] = artifact_id
        result["user_id"] = user_id
        result["submitted_at"] = datetime.now(timezone.utc).isoformat()
        result["correct_count"] = sum(1 for answer in answers if answer.get("is_correct"))
        result["total_possible"] = round(sum(_answer_possible_points(answer) for answer in answers), 4)
        result["accuracy"] = round(result["correct_count"] / len(answers), 4) if answers else 0.0
        attempts_dir = self._question_artifact_folder_for_existing(
            user_id=user_id,
            artifact_id=artifact_id,
        ) / "attempts"
        attempts_dir.mkdir(parents=True, exist_ok=True)
        attempt_path = attempts_dir / f"{result['attempt_id']}.json"
        attempt_path.write_text(
            json.dumps({**result, "answers": answers}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        result["attempt_path"] = self._relative(attempt_path)
        return result

    def save_operation_submission_review(
        self,
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
    ) -> dict[str, Any]:
        operation_id = f"operation_{safe_segment(task_id)}"
        operation_folder = (
            user_root(self.config.storage_root, user_id)
            / "questions"
            / "path_generated"
            / _chapter_group(chapter_id)
            / _chapter_segment(chapter_id)
            / operation_id
        )
        operation_folder.mkdir(parents=True, exist_ok=True)
        manifest_path = operation_folder / "manifest.json"
        manifest = {
            "operation_id": operation_id,
            "source": "path_generated",
            "question_source": "course_resources",
            "user_id": user_id,
            "request_id": request_id,
            "course_id": course_id,
            "chapter_id": chapter_id,
            "chapter_group": _chapter_group(chapter_id),
            "task_id": task_id,
            "workpiece_id": workpiece_id,
            "submissions_path": self._relative(operation_folder / "submissions"),
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        submission_id = f"submission_{uuid4().hex[:12]}"
        submission_folder = operation_folder / "submissions" / submission_id
        images_folder = submission_folder / "uploaded_images"
        images_folder.mkdir(parents=True, exist_ok=True)
        saved_images = self._save_uploaded_images(images_folder, uploaded_images or [])

        submission = {
            "submission_id": submission_id,
            "user_id": user_id,
            "request_id": request_id,
            "course_id": course_id,
            "chapter_id": chapter_id,
            "task_id": task_id,
            "workpiece_id": workpiece_id,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "uploaded_images": saved_images,
            "measurement_params_ref": "measurement_params.json",
        }
        (submission_folder / "submission.json").write_text(
            json.dumps(submission, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _write_json(submission_folder / "measurement_params.json", measurement_params)
        _write_json(submission_folder / "vl_analysis_result.json", vl_analysis_result or {})
        _write_json(submission_folder / "measurement_comparison_result.json", measurement_comparison_result or {})
        _write_json(submission_folder / "operation_review_result.json", operation_review_result or {})
        (submission_folder / "llm_review_report.md").write_text(str(llm_review_report or ""), encoding="utf-8")
        return {
            "operation_id": operation_id,
            "submission_id": submission_id,
            "operation_path": self._relative(operation_folder),
            "submission_path": self._relative(submission_folder),
            "manifest_path": self._relative(manifest_path),
            "saved_images": saved_images,
        }

    def create_qa_session(self, *, user_id: str, course_id: str, title: str) -> dict[str, Any]:
        session = self.repository.create_qa_session(user_id, course_id, title)
        folder = self._qa_folder(user_id=user_id, session_id=session["session_id"])
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "attachments").mkdir(exist_ok=True)
        (folder / "exports").mkdir(exist_ok=True)
        manifest = {
            "session_id": session["session_id"],
            "user_id": user_id,
            "course_id": course_id,
            "title": title,
            "artifact_type": "qa_session",
            "files": {
                "messages": "messages.jsonl",
                "transcript": "transcript.md",
            },
        }
        (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        (folder / "messages.jsonl").touch()
        (folder / "transcript.md").write_text(f"# {title}\n", encoding="utf-8")
        return session

    def save_qa_message(
        self,
        *,
        session_id: str,
        user_id: str,
        role: str,
        content: str,
        related_artifact_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        message = self.repository.save_qa_message(
            session_id=session_id,
            user_id=user_id,
            role=role,
            content=content,
            related_artifact_id=related_artifact_id,
            metadata=metadata,
        )
        self._append_qa_message_file(
            session_id=session_id,
            user_id=user_id,
            role=role,
            content=content,
            related_artifact_id=related_artifact_id,
            metadata=metadata,
            message_id=message["message_id"],
        )
        return message

    def load_qa_session_context(
        self,
        *,
        user_id: str,
        session_id: str,
        max_messages: int = 20,
    ) -> dict[str, Any]:
        folder = self._qa_folder(user_id=user_id, session_id=session_id)
        messages_path = folder / "messages.jsonl"
        messages: list[dict[str, Any]] = []
        if messages_path.exists():
            for raw_line in messages_path.read_text(encoding="utf-8").splitlines():
                if not raw_line.strip():
                    continue
                try:
                    message = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                if isinstance(message, dict):
                    messages.append(message)
        if max_messages > 0:
            messages = messages[-max_messages:]
        return {
            "session_id": session_id,
            "user_id": user_id,
            "messages": messages,
            "context_text": _qa_context_text(messages),
            "manifest_path": self._relative(folder / "manifest.json") if (folder / "manifest.json").exists() else "",
            "messages_path": self._relative(messages_path) if messages_path.exists() else "",
            "transcript_path": self._relative(folder / "transcript.md") if (folder / "transcript.md").exists() else "",
        }

    def _relative(self, path: Path) -> str:
        return str(path.relative_to(self.config.storage_root)).replace("\\", "/")

    def _question_artifact_folder(self, *, user_id: str, artifact_id: str, metadata: dict[str, Any]) -> Path:
        questions_root = user_root(self.config.storage_root, user_id) / "questions"
        if _question_scope(metadata) == "custom_generated":
            return questions_root / "custom_generated" / safe_segment(artifact_id)
        chapter_id = str(metadata.get("chapter_id") or "").strip()
        return (
            questions_root
            / "path_generated"
            / _chapter_group(chapter_id)
            / _chapter_segment(chapter_id or "unassigned")
            / safe_segment(artifact_id)
        )

    def _question_artifact_folder_for_existing(self, *, user_id: str, artifact_id: str) -> Path:
        row = self.repository.get_generated_artifact(artifact_id, user_id=user_id)
        if row is None:
            return self.artifact_store.folder_for(user_id=user_id, artifact_type="quiz", artifact_id=artifact_id)
        try:
            metadata = json.loads(str(row.get("metadata_json") or "{}"))
        except json.JSONDecodeError:
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        metadata.setdefault("chapter_id", row.get("chapter_id") or "")
        return self._question_artifact_folder(user_id=user_id, artifact_id=artifact_id, metadata=metadata)

    def _save_uploaded_images(self, folder: Path, images: list[dict[str, Any]]) -> list[dict[str, Any]]:
        saved = []
        for index, image in enumerate(images, start=1):
            filename = _file_segment(str(image.get("filename") or image.get("name") or f"image_{index}.jpg"))
            if "." not in filename:
                filename = f"{filename}.jpg"
            target = folder / filename
            if image.get("content_base64"):
                target.write_bytes(base64.b64decode(str(image["content_base64"])))
            elif image.get("path"):
                source = Path(str(image["path"]))
                if source.exists() and source.is_file():
                    shutil.copy2(source, target)
            saved.append(
                {
                    "name": str(image.get("name") or filename),
                    "filename": filename,
                    "path": self._relative(target),
                    "exists": target.exists(),
                }
            )
        return saved

    def _copy_markdown_assets(self, artifact_folder: Path, markdown: str, roots: Any) -> list[str]:
        if not isinstance(roots, list):
            return []
        asset_roots = [Path(str(root)).expanduser() for root in roots if str(root).strip()]
        copied: list[str] = []
        seen: set[str] = set()
        for raw_ref in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", markdown):
            reference = raw_ref.strip().strip("<>").split("#", 1)[0].split("?", 1)[0]
            if not reference or reference.startswith(("http://", "https://", "data:")):
                continue
            relative = Path(reference.replace("/", "\\"))
            if relative.is_absolute() or ".." in relative.parts:
                continue
            destination = artifact_folder / relative
            relative_key = str(relative).replace("\\", "/")
            if relative_key in seen:
                continue
            source = next((root / relative for root in asset_roots if (root / relative).is_file()), None)
            if source is None:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            copied.append(self._relative(destination))
            seen.add(relative_key)
        return copied

    def _qa_folder(self, *, user_id: str, session_id: str) -> Path:
        return user_root(self.config.storage_root, user_id) / "conversations" / safe_segment(session_id)

    def _append_qa_message_file(
        self,
        *,
        session_id: str,
        user_id: str,
        role: str,
        content: str,
        related_artifact_id: str | None,
        metadata: dict[str, Any] | None,
        message_id: str,
    ) -> None:
        folder = self._qa_folder(user_id=user_id, session_id=session_id)
        folder.mkdir(parents=True, exist_ok=True)
        message = {
            "message_id": message_id,
            "session_id": session_id,
            "user_id": user_id,
            "role": role,
            "content": content,
            "related_artifact_id": related_artifact_id,
            "metadata": metadata or {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        messages_path = folder / "messages.jsonl"
        with messages_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(message, ensure_ascii=False) + "\n")
        self._write_qa_transcript(folder, title=session_id)

    def _write_qa_transcript(self, folder: Path, *, title: str) -> None:
        messages_path = folder / "messages.jsonl"
        lines = [f"# {title}", ""]
        if messages_path.exists():
            for raw_line in messages_path.read_text(encoding="utf-8").splitlines():
                if not raw_line.strip():
                    continue
                message = json.loads(raw_line)
                role = str(message.get("role") or "message")
                content = str(message.get("content") or "")
                lines.extend([f"## {role}", "", content, ""])
        (folder / "transcript.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _quiz_item_from_question(question: dict[str, Any]) -> dict[str, Any]:
    return {
        "item_id": question.get("id") or question.get("item_id"),
        "question_text": question.get("question_text") or question.get("stem") or "",
        "question_type": question.get("type") or question.get("question_type") or "single_choice",
        "options": question.get("options") or [],
        "correct_answer": question.get("correct_answer", question.get("answer")),
        "explanation": question.get("explanation") or "",
        "knowledge_points": question.get("knowledge_points") or [],
        "difficulty": question.get("difficulty") or "",
    }


def _qa_context_text(messages: list[dict[str, Any]]) -> str:
    lines = []
    for message in messages:
        role = str(message.get("role") or "message")
        content = str(message.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _question_scope(metadata: dict[str, Any]) -> str:
    value = str(metadata.get("question_scope") or metadata.get("question_collection") or "").strip()
    if value == "custom_generated":
        return "custom_generated"
    chapter_id = str(metadata.get("chapter_id") or "").strip()
    return "path_generated" if chapter_id else "custom_generated"


def _chapter_group(chapter_id: str) -> str:
    prefix = str(chapter_id or "").split(".", 1)[0]
    try:
        number = int(prefix)
    except ValueError:
        return "chapter_misc"
    return f"chapter_{number:02d}"


def _chapter_segment(chapter_id: str) -> str:
    return "".join(char if char.isalnum() or char in {"_", "-", "."} else "_" for char in str(chapter_id))


def _file_segment(filename: str) -> str:
    return "".join(char if char.isalnum() or char in {"_", "-", "."} else "_" for char in str(filename))


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _answer_possible_points(answer: dict[str, Any]) -> float:
    for value in (answer.get("possible"), answer.get("max_score")):
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return 1.0


def _manifest_for(row: dict[str, Any], *, exported: dict[str, Path]) -> dict[str, Any]:
    files = {
        "markdown": row.get("markdown_path", ""),
    }
    if "docx" in exported:
        files["docx"] = row.get("docx_path", "")
    if "pdf" in exported:
        files["pdf"] = row.get("pdf_path", "")
    if row.get("markdown_assets"):
        files["assets"] = row.get("markdown_assets", [])
    return {
        "artifact_id": row.get("artifact_id", ""),
        "user_id": row.get("user_id", ""),
        "title": row.get("title", ""),
        "course_id": row.get("course_id", ""),
        "chapter_id": row.get("chapter_id", ""),
        "artifact_type": row.get("artifact_type", ""),
        "source_node": row.get("source_node", ""),
        "files": files,
    }
