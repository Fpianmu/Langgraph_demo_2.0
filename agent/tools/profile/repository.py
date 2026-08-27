from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4


METRIC_FIELDS = {"theory_score", "safety_score", "operation_score", "programming_score", "confidence"}
PROFILE_SCORE_FIELDS = {"overall", "dimensions", "source", "updated_at"}


class ProfileRepository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def get_or_create_user(
        self,
        user_id: str,
        *,
        display_name: str | None = None,
        background_type: str | None = None,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT user_id, display_name, background_type FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO users (user_id, display_name, background_type, created_at, updated_at)
                    VALUES (?, ?, ?, datetime('now'), datetime('now'))
                    """,
                    (user_id, display_name or user_id, background_type or ""),
                )
                conn.execute(
                    """
                    INSERT INTO learner_metrics (
                        user_id, theory_score, safety_score, operation_score, programming_score, confidence, updated_at
                    )
                    VALUES (?, 0, 0, 0, 0, 0, datetime('now'))
                    """,
                    (user_id,),
                )
                row = conn.execute("SELECT user_id, display_name, background_type FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return dict(row)

    def get_metrics(self, user_id: str) -> dict[str, float]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT theory_score, safety_score, operation_score, programming_score, confidence
                FROM learner_metrics WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
        if row is None:
            return {field: 0.0 for field in METRIC_FIELDS}
        return {key: float(row[key] or 0.0) for key in row.keys()}

    def get_capability_assessment(self, user_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT capability_assessment_json
                FROM learner_metrics WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        raw = row["capability_assessment_json"] if "capability_assessment_json" in row.keys() else None
        if not raw:
            return None
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None

    def get_capability_profile_score(self, user_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT capability_profile_score_json
                FROM learner_metrics WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        raw = row["capability_profile_score_json"] if "capability_profile_score_json" in row.keys() else None
        if not raw:
            return None
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None

    def set_capability_assessment(self, user_id: str, document: dict[str, Any]) -> None:
        payload = json.dumps(document, ensure_ascii=False)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT capability_assessment_json
                FROM learner_metrics WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
            current = row["capability_assessment_json"] if row is not None and "capability_assessment_json" in row.keys() else None
            if current == payload:
                return
            conn.execute(
                """
                UPDATE learner_metrics
                SET capability_assessment_json = ?, updated_at = datetime('now')
                WHERE user_id = ?
                """,
                (payload, user_id),
            )

    def set_capability_profile_score(self, user_id: str, document: dict[str, Any]) -> None:
        payload = json.dumps(document, ensure_ascii=False)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT capability_profile_score_json
                FROM learner_metrics WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
            current = row["capability_profile_score_json"] if row is not None and "capability_profile_score_json" in row.keys() else None
            if current == payload:
                return
            conn.execute(
                """
                UPDATE learner_metrics
                SET capability_profile_score_json = ?, updated_at = datetime('now')
                WHERE user_id = ?
                """,
                (payload, user_id),
            )

    def update_metrics(self, user_id: str, patches: list[dict[str, Any]]) -> list[dict[str, Any]]:
        applied = []
        metrics = self.get_metrics(user_id)
        with self._connect() as conn:
            for patch in patches:
                field = str(patch.get("field") or "")
                if field not in METRIC_FIELDS:
                    continue
                if "value" in patch:
                    new_value = _clamp_score(patch.get("value"))
                else:
                    delta = _clamp_delta(patch.get("delta", 0))
                    new_value = _clamp_score(metrics.get(field, 0.0) + delta)
                metrics[field] = new_value
                conn.execute(
                    f"UPDATE learner_metrics SET {field} = ?, updated_at = datetime('now') WHERE user_id = ?",
                    (new_value, user_id),
                )
                applied.append({"field": field, "value": new_value, "reason": str(patch.get("reason") or "")})
        return applied

    def upsert_knowledge_gaps(self, user_id: str, patches: list[dict[str, Any]]) -> list[dict[str, Any]]:
        applied = []
        with self._connect() as conn:
            for patch in patches:
                concept = str(patch.get("concept") or "").strip()
                evidence = str(patch.get("evidence") or "").strip()
                if not concept or not evidence:
                    continue
                gap_id = str(patch.get("gap_id") or f"gap_{uuid4().hex[:12]}")
                row = {
                    "gap_id": gap_id,
                    "user_id": user_id,
                    "knowledge_point_id": str(patch.get("knowledge_point_id") or "").strip(),
                    "concept": concept,
                    "chapter_id": str(patch.get("chapter_id") or "").strip(),
                    "category": str(patch.get("category") or "").strip(),
                    "severity": str(patch.get("severity") or "medium"),
                    "score": _clamp_unit(patch.get("score", 0.0)),
                    "evidence": evidence,
                    "evidence_items_json": json.dumps(_list_of_dicts(patch.get("evidence_items")), ensure_ascii=False),
                    "recommended_actions_json": json.dumps(_list_of_strings(patch.get("recommended_actions")), ensure_ascii=False),
                    "status": str(patch.get("status") or "open"),
                    "source": str(patch.get("source") or "llm_suggestion"),
                }
                conn.execute(
                    """
                    INSERT INTO knowledge_gaps (
                        gap_id, user_id, knowledge_point_id, concept, chapter_id, category, severity, score,
                        evidence, evidence_items_json, recommended_actions_json, status, source, updated_at
                    )
                    VALUES (
                        :gap_id, :user_id, :knowledge_point_id, :concept, :chapter_id, :category, :severity, :score,
                        :evidence, :evidence_items_json, :recommended_actions_json, :status, :source, datetime('now')
                    )
                    ON CONFLICT(gap_id) DO UPDATE SET
                        knowledge_point_id=excluded.knowledge_point_id,
                        concept=excluded.concept,
                        chapter_id=excluded.chapter_id,
                        category=excluded.category,
                        severity=excluded.severity,
                        score=excluded.score,
                        evidence=excluded.evidence,
                        evidence_items_json=excluded.evidence_items_json,
                        recommended_actions_json=excluded.recommended_actions_json,
                        status=excluded.status,
                        source=excluded.source,
                        updated_at=datetime('now')
                    """,
                    row,
                )
                applied.append(row)
        return applied

    def upsert_learning_progress(self, user_id: str, patches: list[dict[str, Any]]) -> list[dict[str, Any]]:
        applied = []
        with self._connect() as conn:
            for patch in patches:
                course_id = str(patch.get("course_id") or "").strip()
                chapter_id = str(patch.get("chapter_id") or "").strip()
                if not course_id or not chapter_id:
                    continue
                path_id = str(patch.get("path_id") or "").strip()
                default_progress_id = (
                    f"{user_id}_{course_id}_{path_id}_{chapter_id}"
                    if path_id
                    else f"{user_id}_{course_id}_{chapter_id}"
                )
                progress_id = str(patch.get("progress_id") or default_progress_id)
                row = {
                    "progress_id": progress_id,
                    "user_id": user_id,
                    "course_id": course_id,
                    "path_id": path_id,
                    "path_version": str(patch.get("path_version") or ""),
                    "chapter_id": chapter_id,
                    "chapter_order": _non_negative_int(patch.get("chapter_order")),
                    "assignment_updated_at": str(patch.get("assignment_updated_at") or ""),
                    "status": str(patch.get("status") or "learning"),
                    "completion_rate": _clamp_unit(patch.get("completion_rate", 0.0)),
                }
                conn.execute(
                    """
                    INSERT INTO learning_progress (
                        progress_id, user_id, course_id, path_id, path_version, chapter_id, chapter_order,
                        assignment_updated_at, status, completion_rate, last_activity_at, updated_at
                    )
                    VALUES (
                        :progress_id, :user_id, :course_id, :path_id, :path_version, :chapter_id, :chapter_order,
                        :assignment_updated_at, :status, :completion_rate, datetime('now'), datetime('now')
                    )
                    ON CONFLICT(progress_id) DO UPDATE SET
                        path_id=excluded.path_id,
                        path_version=excluded.path_version,
                        chapter_order=excluded.chapter_order,
                        assignment_updated_at=excluded.assignment_updated_at,
                        status=excluded.status,
                        completion_rate=excluded.completion_rate,
                        last_activity_at=datetime('now'),
                        updated_at=datetime('now')
                    """,
                    row,
                )
                applied.append(row)
        return applied

    def list_knowledge_gaps(self, user_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT gap_id, knowledge_point_id, concept, chapter_id, category, severity, score,
                       evidence, evidence_items_json, recommended_actions_json, status, source, updated_at
                FROM knowledge_gaps WHERE user_id = ? ORDER BY updated_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_learning_progress(self, user_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT progress_id, course_id, path_id, path_version, chapter_id, chapter_order,
                       assignment_updated_at, status, completion_rate, last_activity_at, updated_at
                FROM learning_progress WHERE user_id = ? ORDER BY updated_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def append_resource_difficulty_record(self, user_id: str, record: dict[str, Any]) -> dict[str, Any]:
        record_id = str(record.get("record_id") or f"resource_diff_{uuid4().hex[:12]}")
        values = {
            "record_id": record_id,
            "user_id": user_id,
            "resource_id": str(record.get("resource_id") or ""),
            "resource_type": str(record.get("resource_type") or ""),
            "chapter_id": str(record.get("chapter_id") or ""),
            "profile_score": _clamp_score(record.get("profile_score")),
            "resource_difficulty": _clamp_score(record.get("resource_difficulty")),
            "difficulty_delta": _clamp_resource_delta(record.get("difficulty_delta")),
            "alignment_score": _clamp_score(record.get("alignment_score", 0.0)),
            "source_node": str(record.get("source_node") or ""),
            "resource_meta_json": json.dumps(record.get("resource_meta") or {}, ensure_ascii=False),
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO resource_difficulty_records (
                    record_id, user_id, resource_id, resource_type, chapter_id, profile_score,
                    resource_difficulty, difficulty_delta, alignment_score, source_node, resource_meta_json,
                    created_at
                )
                VALUES (
                    :record_id, :user_id, :resource_id, :resource_type, :chapter_id, :profile_score,
                    :resource_difficulty, :difficulty_delta, :alignment_score, :source_node, :resource_meta_json,
                    datetime('now')
                )
                """,
                values,
            )
        return values

    def list_resource_difficulty_records(self, user_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT record_id, user_id, resource_id, resource_type, chapter_id, profile_score,
                       resource_difficulty, difficulty_delta, alignment_score, source_node, resource_meta_json,
                       created_at
                FROM resource_difficulty_records
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, max(int(limit), 1)),
            ).fetchall()
        records = []
        for row in rows:
            item = dict(row)
            meta_raw = item.get("resource_meta_json")
            if isinstance(meta_raw, str) and meta_raw:
                try:
                    item["resource_meta"] = json.loads(meta_raw)
                except json.JSONDecodeError:
                    item["resource_meta"] = {}
            else:
                item["resource_meta"] = {}
            records.append(item)
        return records

    def upsert_path_assignment(self, user_id: str, assignment: dict[str, Any]) -> dict[str, Any]:
        course_id = str(assignment.get("course_id") or "").strip()
        learner_level = str(assignment.get("learner_level") or "").strip()
        path_id = str(assignment.get("path_id") or "").strip()
        if not course_id or not learner_level or not path_id:
            raise ValueError("course_id, learner_level and path_id are required")
        score = assignment.get("classification_score")
        if score is not None:
            try:
                score = float(score)
            except (TypeError, ValueError) as exc:
                raise ValueError("classification_score must be numeric") from exc
        values = {
            "user_id": user_id,
            "course_id": course_id,
            "learner_level": learner_level,
            "path_id": path_id,
            "path_version": str(assignment.get("path_version") or ""),
            "classification_source": str(assignment.get("classification_source") or "registration"),
            "classification_score": score,
            "classification_reason": str(assignment.get("classification_reason") or ""),
            "manual_override": 1 if assignment.get("manual_override") else 0,
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_course_path_assignments (
                    user_id, course_id, learner_level, path_id, path_version,
                    classification_source, classification_score, classification_reason,
                    manual_override, assigned_at, updated_at
                )
                VALUES (
                    :user_id, :course_id, :learner_level, :path_id, :path_version,
                    :classification_source, :classification_score, :classification_reason,
                    :manual_override, datetime('now'), datetime('now')
                )
                ON CONFLICT(user_id, course_id) DO UPDATE SET
                    learner_level=excluded.learner_level,
                    path_id=excluded.path_id,
                    path_version=excluded.path_version,
                    classification_source=excluded.classification_source,
                    classification_score=excluded.classification_score,
                    classification_reason=excluded.classification_reason,
                    manual_override=excluded.manual_override,
                    updated_at=datetime('now')
                """,
                values,
            )
        result = self.get_path_assignment(user_id, course_id)
        if result is None:
            raise RuntimeError("path assignment was not persisted")
        return result

    def get_path_assignment(self, user_id: str, course_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT user_id, course_id, learner_level, path_id, path_version,
                       classification_source, classification_score, classification_reason,
                       manual_override, assigned_at, updated_at
                FROM user_course_path_assignments
                WHERE user_id = ? AND course_id = ?
                """,
                (user_id, course_id),
            ).fetchone()
        return _path_assignment_from_row(row)

    def list_path_assignments(self, user_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT user_id, course_id, learner_level, path_id, path_version,
                       classification_source, classification_score, classification_reason,
                       manual_override, assigned_at, updated_at
                FROM user_course_path_assignments
                WHERE user_id = ? ORDER BY course_id
                """,
                (user_id,),
            ).fetchall()
        return [_path_assignment_from_row(row) for row in rows if row is not None]

    def record_update_event(self, user_id: str, request_id: str, payload: dict[str, Any], accepted: bool, reason: str) -> str:
        event_id = f"profile_evt_{uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO profile_update_events (
                    event_id, user_id, request_id, source_node, update_payload_json, accepted, reason, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    event_id,
                    user_id,
                    request_id,
                    str(payload.get("source_node") or "profile_tool"),
                    json.dumps(payload, ensure_ascii=False),
                    1 if accepted else 0,
                    reason,
                ),
            )
        return event_id

    @contextmanager
    def _connect(self) -> sqlite3.Connection:
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
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    display_name TEXT,
                    background_type TEXT,
                    created_at TEXT,
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS learner_metrics (
                    user_id TEXT PRIMARY KEY,
                    theory_score REAL,
                    safety_score REAL,
                    operation_score REAL,
                    programming_score REAL,
                    confidence REAL,
                    capability_assessment_json TEXT,
                    capability_profile_score_json TEXT,
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS knowledge_gaps (
                    gap_id TEXT PRIMARY KEY,
                    user_id TEXT,
                    knowledge_point_id TEXT,
                    concept TEXT,
                    chapter_id TEXT,
                    category TEXT,
                    severity TEXT,
                    score REAL,
                    evidence TEXT,
                    evidence_items_json TEXT,
                    recommended_actions_json TEXT,
                    status TEXT,
                    source TEXT,
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS learning_progress (
                    progress_id TEXT PRIMARY KEY,
                    user_id TEXT,
                    course_id TEXT,
                    path_id TEXT,
                    path_version TEXT,
                    chapter_id TEXT,
                    chapter_order INTEGER,
                    assignment_updated_at TEXT,
                    status TEXT,
                    completion_rate REAL,
                    last_activity_at TEXT,
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS profile_update_events (
                    event_id TEXT PRIMARY KEY,
                    user_id TEXT,
                    request_id TEXT,
                    source_node TEXT,
                    update_payload_json TEXT,
                    accepted INTEGER,
                    reason TEXT,
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS user_course_path_assignments (
                    user_id TEXT NOT NULL,
                    course_id TEXT NOT NULL,
                    learner_level TEXT NOT NULL,
                    path_id TEXT NOT NULL,
                    path_version TEXT,
                    classification_source TEXT,
                    classification_score REAL,
                    classification_reason TEXT,
                    manual_override INTEGER DEFAULT 0,
                    assigned_at TEXT,
                    updated_at TEXT,
                    PRIMARY KEY (user_id, course_id)
                );
                CREATE TABLE IF NOT EXISTS resource_difficulty_records (
                    record_id TEXT PRIMARY KEY,
                    user_id TEXT,
                    resource_id TEXT,
                    resource_type TEXT,
                    chapter_id TEXT,
                    profile_score REAL,
                    resource_difficulty REAL,
                    difficulty_delta REAL,
                    alignment_score REAL,
                    source_node TEXT,
                    resource_meta_json TEXT,
                    created_at TEXT
                );
                """
            )
            _ensure_columns(
                conn,
                "learner_metrics",
                {
                    "capability_assessment_json": "TEXT",
                    "capability_profile_score_json": "TEXT",
                },
            )
            _ensure_columns(
                conn,
                "knowledge_gaps",
                {
                    "knowledge_point_id": "TEXT",
                    "chapter_id": "TEXT",
                    "category": "TEXT",
                    "score": "REAL",
                    "evidence_items_json": "TEXT",
                    "recommended_actions_json": "TEXT",
                },
            )
            _ensure_columns(
                conn,
                "learning_progress",
                {
                    "path_id": "TEXT",
                    "path_version": "TEXT",
                    "chapter_order": "INTEGER",
                    "assignment_updated_at": "TEXT",
                },
            )
            _ensure_columns(
                conn,
                "resource_difficulty_records",
                {
                    "resource_meta_json": "TEXT",
                    "alignment_score": "REAL",
                },
            )


def _clamp_score(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = 0.0
    return min(max(parsed, 0.0), 100.0)


def _clamp_delta(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = 0.0
    return min(max(parsed, -5.0), 5.0)


def _clamp_resource_delta(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = 0.0
    return min(max(parsed, -100.0), 100.0)


def _clamp_unit(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = 0.0
    return min(max(parsed, 0.0), 1.0)


def _non_negative_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(parsed, 0)


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _ensure_columns(conn: sqlite3.Connection, table_name: str, columns: dict[str, str]) -> None:
    existing = {
        str(row["name"])
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    for name, column_type in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {name} {column_type}")


def _path_assignment_from_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    result["manual_override"] = bool(result.get("manual_override"))
    return result
