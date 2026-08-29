from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.tools.learning_archive.manager import LearningArchiveManager
from agent.tools.profile.manager import ProfileManager
from agent.tools.quiz_profile_sync_tools import sync_quiz_profile_evidence


class UserCenterDataPipelineTests(unittest.TestCase):
    def test_quiz_evidence_updates_capability_and_real_chapter_gap(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            result = sync_quiz_profile_evidence(
                user_id="learner_001",
                course_id="cnc_lathe",
                request_id="req_quiz_sync",
                storage_root=root,
                evidence=[
                    {
                        "id": "evidence_1",
                        "attemptId": "attempt_1",
                        "sourceType": "quiz",
                        "dimension": "safety",
                        "topic": "开机前安全检查",
                        "knowledgePoint": "急停与防护门检查",
                        "knowledgePointId": "cnc_lathe.2.1.safety_check",
                        "correct": False,
                        "earned": 0,
                        "possible": 2,
                        "difficulty": "easy",
                        "occurredAt": "2026-08-29T09:00:00+00:00",
                        "sourceRefs": ["safety_manual.pdf"],
                        "ragChunkIds": ["chunk_1"],
                        "questionType": "single_choice",
                        "attemptNumber": 1,
                        "itemRevision": "q1",
                        "dimensionSource": "declared",
                        "questionGrounded": True,
                        "reviewStatus": "auto_verified",
                        "chapterId": "2.1",
                        "objectiveIds": ["2.1:safety"],
                    }
                    ,
                    {
                        "id": "evidence_2",
                        "attemptId": "attempt_1",
                        "sourceType": "quiz",
                        "dimension": "safety",
                        "topic": "开机前安全检查",
                        "knowledgePoint": "开机前还需要确认哪些防护装置？",
                        "knowledgePointId": "开机前还需要确认哪些防护装置",
                        "correct": True,
                        "earned": 2,
                        "possible": 2,
                        "difficulty": "easy",
                        "occurredAt": "2026-08-29T09:01:00+00:00",
                        "sourceRefs": ["safety_manual.pdf"],
                        "ragChunkIds": ["chunk_2"],
                        "questionType": "single_choice",
                        "attemptNumber": 1,
                        "itemRevision": "q2",
                        "dimensionSource": "declared",
                        "questionGrounded": True,
                        "reviewStatus": "auto_verified",
                        "chapterId": "2.1",
                        "objectiveIds": ["2.1:safety"],
                    },
                ],
            )
            self.assertEqual(result["applied_capability_evidence_count"], 2)
            self.assertGreater(result["capability_profile_score"]["dimensions"]["safety"], 0)
            self.assertEqual(len(result["knowledge_gaps"]), 2)
            self.assertTrue(all(item["chapter_id"] == "2.1" for item in result["knowledge_gaps"]))
            self.assertTrue(all(item["evidence_items_json"] != "[]" for item in result["knowledge_gaps"]))

    def test_legacy_question_stems_collapse_into_one_conceptual_gap(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            shared = {
                "attemptId": "attempt_legacy",
                "sourceType": "quiz",
                "dimension": "safety",
                "topic": "数控机床安全操作",
                "correct": False,
                "earned": 0,
                "possible": 2,
                "difficulty": "easy",
                "sourceRefs": ["safety_manual.pdf"],
                "ragChunkIds": ["chunk_1"],
                "questionType": "single_choice",
                "attemptNumber": 1,
                "dimensionSource": "declared",
                "questionGrounded": True,
                "reviewStatus": "auto_verified",
                "chapterId": "2.1",
            }
            result = sync_quiz_profile_evidence(
                user_id="learner_legacy",
                course_id="cnc_lathe",
                request_id="req_legacy_sync",
                storage_root=Path(folder),
                evidence=[
                    {
                        **shared,
                        "id": "legacy_1",
                        "knowledgePoint": "开机前必须完成哪些安全检查？",
                        "knowledgePointId": "开机前必须完成哪些安全检查",
                        "occurredAt": "2026-08-29T09:00:00+00:00",
                    },
                    {
                        **shared,
                        "id": "legacy_2",
                        "knowledgePoint": "发生异常报警时首先应该做什么？",
                        "knowledgePointId": "发生异常报警时首先应该做什么",
                        "occurredAt": "2026-08-29T09:01:00+00:00",
                    },
                ],
            )
            self.assertEqual(len(result["knowledge_gaps"]), 1)
            self.assertEqual(result["knowledge_gaps"][0]["concept"], "数控机床安全操作 · 安全规范")

    def test_resource_trace_backfills_saved_materials(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = LearningArchiveManager(root)
            saved = archive.save_generated_artifact(
                user_id="learner_002",
                request_id="req_lecture",
                artifact_type="lecture",
                title="安全基础讲义",
                markdown_content="# 安全基础",
                metadata={"course_id": "cnc_lathe", "chapter_id": "2.1"},
            )
            trace = ProfileManager(root).load_resource_difficulty_trace("learner_002")
            self.assertEqual(trace["record_count"], 1)
            self.assertEqual(trace["resource_difficulty_records"][0]["resource_id"], saved["artifact_id"])
            self.assertGreater(trace["resource_difficulty_records"][0]["resource_difficulty"], 0)


if __name__ == "__main__":
    unittest.main()
