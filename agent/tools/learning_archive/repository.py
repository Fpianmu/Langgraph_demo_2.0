from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4


class ArchiveRepository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def insert_artifact(self, row: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO generated_artifacts (
                    artifact_id, user_id, request_id, artifact_type, title, course_id, chapter_id,
                    source_node, markdown_path, docx_path, pdf_path, metadata_json, created_at, updated_at
                )
                VALUES (
                    :artifact_id, :user_id, :request_id, :artifact_type, :title, :course_id, :chapter_id,
                    :source_node, :markdown_path, :docx_path, :pdf_path, :metadata_json, datetime('now'), datetime('now')
                )
                """,
                row,
            )

    def get_generated_artifact(self, artifact_id: str, user_id: str | None = None) -> dict[str, Any] | None:
        query = "SELECT * FROM generated_artifacts WHERE artifact_id = ?"
        params: list[Any] = [artifact_id]
        if user_id is not None:
            query += " AND user_id = ?"
            params.append(user_id)
        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
        return dict(row) if row is not None else None

    def insert_quiz_items(self, artifact_id: str, user_id: str, items: list[dict[str, Any]]) -> list[str]:
        item_ids = []
        with self._connect() as conn:
            for item in items:
                item_id = str(item.get("item_id") or f"item_{uuid4().hex[:12]}")
                item_ids.append(item_id)
                conn.execute(
                    """
                    INSERT INTO quiz_items (
                        item_id, artifact_id, user_id, question_text, question_type, options_json,
                        correct_answer_json, explanation, knowledge_points_json, difficulty, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    """,
                    (
                        item_id,
                        artifact_id,
                        user_id,
                        str(item.get("question_text") or ""),
                        str(item.get("question_type") or "short_answer"),
                        json.dumps(item.get("options") or [], ensure_ascii=False),
                        json.dumps(item.get("correct_answer"), ensure_ascii=False),
                        str(item.get("explanation") or ""),
                        json.dumps(item.get("knowledge_points") or [], ensure_ascii=False),
                        str(item.get("difficulty") or ""),
                    ),
                )
        return item_ids

    def insert_quiz_attempt(self, user_id: str, artifact_id: str, answers: list[dict[str, Any]]) -> dict[str, Any]:
        attempt_id = f"attempt_{uuid4().hex[:12]}"
        score = float(sum(float(answer.get("score") or 0.0) for answer in answers))
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO quiz_attempts (
                    attempt_id, artifact_id, user_id, started_at, submitted_at, score, result_summary_json
                )
                VALUES (?, ?, ?, datetime('now'), datetime('now'), ?, ?)
                """,
                (attempt_id, artifact_id, user_id, score, json.dumps({"answer_count": len(answers)}, ensure_ascii=False)),
            )
            for answer in answers:
                conn.execute(
                    """
                    INSERT INTO quiz_answers (
                        answer_id, attempt_id, item_id, user_answer_json, is_correct, score, feedback, answered_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    """,
                    (
                        f"answer_{uuid4().hex[:12]}",
                        attempt_id,
                        str(answer.get("item_id") or ""),
                        json.dumps(answer.get("user_answer"), ensure_ascii=False),
                        1 if bool(answer.get("is_correct")) else 0,
                        float(answer.get("score") or 0.0),
                        str(answer.get("feedback") or ""),
                    ),
                )
        return {"attempt_id": attempt_id, "score": score, "answer_count": len(answers)}

    def create_qa_session(self, user_id: str, course_id: str, title: str) -> dict[str, Any]:
        session_id = f"qa_{uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO qa_sessions (session_id, user_id, course_id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))
                """,
                (session_id, user_id, course_id, title),
            )
        return {"session_id": session_id, "user_id": user_id, "course_id": course_id, "title": title}

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
        message_id = f"msg_{uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO qa_messages (
                    message_id, session_id, user_id, role, content, related_artifact_id, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    message_id,
                    session_id,
                    user_id,
                    role,
                    content,
                    related_artifact_id,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
            conn.execute("UPDATE qa_sessions SET updated_at = datetime('now') WHERE session_id = ?", (session_id,))
        return {"message_id": message_id, "session_id": session_id, "role": role}

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS generated_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    user_id TEXT,
                    request_id TEXT,
                    artifact_type TEXT,
                    title TEXT,
                    course_id TEXT,
                    chapter_id TEXT,
                    source_node TEXT,
                    markdown_path TEXT,
                    docx_path TEXT,
                    pdf_path TEXT,
                    metadata_json TEXT,
                    created_at TEXT,
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS quiz_items (
                    item_id TEXT PRIMARY KEY,
                    artifact_id TEXT,
                    user_id TEXT,
                    question_text TEXT,
                    question_type TEXT,
                    options_json TEXT,
                    correct_answer_json TEXT,
                    explanation TEXT,
                    knowledge_points_json TEXT,
                    difficulty TEXT,
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS quiz_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    artifact_id TEXT,
                    user_id TEXT,
                    started_at TEXT,
                    submitted_at TEXT,
                    score REAL,
                    result_summary_json TEXT
                );
                CREATE TABLE IF NOT EXISTS quiz_answers (
                    answer_id TEXT PRIMARY KEY,
                    attempt_id TEXT,
                    item_id TEXT,
                    user_answer_json TEXT,
                    is_correct INTEGER,
                    score REAL,
                    feedback TEXT,
                    answered_at TEXT
                );
                CREATE TABLE IF NOT EXISTS qa_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT,
                    course_id TEXT,
                    title TEXT,
                    created_at TEXT,
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS qa_messages (
                    message_id TEXT PRIMARY KEY,
                    session_id TEXT,
                    user_id TEXT,
                    role TEXT,
                    content TEXT,
                    related_artifact_id TEXT,
                    metadata_json TEXT,
                    created_at TEXT
                );
                """
            )
