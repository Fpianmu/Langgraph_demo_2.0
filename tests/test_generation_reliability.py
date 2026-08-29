from __future__ import annotations

import unittest

from agent.api import _normalize_graph_result
from agent.node.hallucination_elimination.safe_reject_node import safe_reject_node
from agent.node.hallucination_elimination.verification_router import verification_router
from agent.node.knowledge_generation.progress_branch_nodes import (
    quiz_context_adapter_node,
    quiz_schema_normalizer_node,
)


def _material(content_type: str) -> dict:
    return {
        "meta": {"content_type": content_type, "status": "success"},
        "title": "测试材料",
        "payload": {"questions": []} if content_type == "quiz" else {"sections": []},
    }


class GenerationReliabilityTests(unittest.TestCase):
    def test_quiz_context_loads_real_chapter_resources(self) -> None:
        result = quiz_context_adapter_node(
            {
                "course_id": "cnc_lathe",
                "chapter_id": "1.1",
                "content_type": "quiz",
                "task": "生成测验",
                "rag_package": {"evidence": []},
            }
        )

        self.assertEqual(result["chapter_resource_load_result"]["status"], "success")
        self.assertTrue(result["manual_lecture_content"])
        self.assertTrue(result["reference_quiz"].get("questions"))
        self.assertTrue(result["quiz_context_adapter_result"]["has_reference_quiz"])

    def test_safe_reject_uses_grounded_chapter_lecture(self) -> None:
        result = safe_reject_node(
            {
                "verification_materials": {"lecture": _material("lecture")},
                "manual_lecture_content": "# 章节标题\n\n可靠正文。\n\n## 安全边界\n\n必须先检查。",
                "rag_package": {"evidence": []},
            }
        )

        material = result["verified_materials"]["lecture"]
        self.assertEqual(result["verification_decision"], "grounded_fallback")
        self.assertEqual(material["meta"]["status"], "success")
        self.assertGreaterEqual(len(material["payload"]["sections"]), 2)

    def test_safe_reject_rebuilds_complete_valid_quiz_batch(self) -> None:
        slots = [
            {
                "sequence": index + 1,
                "question_type": ("single_choice", "true_false", "cloze", "short_answer")[index % 4],
                "difficulty": "easy",
                "points": 1,
                "capability_dimension": "foundations",
            }
            for index in range(10)
        ]
        result = safe_reject_node(
            {
                "course_id": "cnc_lathe",
                "chapter_id": "1.1",
                "verification_materials": {"quiz": _material("quiz")},
                "quiz_blueprint_slots": slots,
                "reference_quiz": {
                    "questions": [
                        {
                            "question_id": "ref_1",
                            "stem": "数控车床的主要组成是什么？",
                            "reference_answer": "由主机、数控装置、驱动装置和辅助装置等组成。",
                            "explanation": "依据章节标准讲义。",
                        }
                    ]
                },
            }
        )

        questions = result["verified_materials"]["quiz"]["payload"]["questions"]
        self.assertEqual(result["verification_decision"], "grounded_fallback")
        self.assertEqual(len(questions), 10)
        self.assertTrue(all(question["question_type"] == slot["question_type"] for question, slot in zip(questions, slots)))
        self.assertTrue(
            all(
                question["answer"] in {"A", "B"}
                for question in questions
                if question["question_type"] == "true_false"
            )
        )

    def test_incomplete_quiz_batch_is_routed_to_grounded_rebuild(self) -> None:
        slots = [
            {"sequence": index + 1, "question_type": "true_false", "points": 1}
            for index in range(10)
        ]
        normalized = quiz_schema_normalizer_node(
            {
                "chapter_id": "1.1",
                "quiz_blueprint_slots": slots,
                "typed_quiz_output": {
                    "meta": {"content_type": "quiz", "status": "success"},
                    "questions": [
                        {
                            "stem": "本节包含基础知识。",
                            "question_type": "true_false",
                            "answer": "A",
                        }
                    ],
                },
            }
        )

        validation = normalized["quiz_schema_validation_result"]
        self.assertEqual(validation["status"], "normalized_with_warnings")
        self.assertTrue(any(item.get("reason") == "question_count_mismatch" for item in validation["errors"]))
        route = verification_router({**normalized, "claim_checks": [{"label": "supported", "evidence_refs": ["x"]}]})
        self.assertEqual(route.goto, "safe_reject_node")

    def test_api_does_not_report_safe_reject_as_success(self) -> None:
        result = _normalize_graph_result(
            {
                "request_id": "req_test",
                "content_type": "quiz",
                "verification_decision": "safe_reject_node",
                "verified_output": _material("quiz"),
            },
            {"request_id": "req_test", "content_type": "quiz"},
            "run_test",
        )

        self.assertEqual(result["status"], "content_rejected")
        self.assertEqual(result["error_type"], "verification_rejected")


if __name__ == "__main__":
    unittest.main()
