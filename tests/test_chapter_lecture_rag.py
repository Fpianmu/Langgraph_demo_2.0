from __future__ import annotations

import unittest

from agent.node.knowledge_generation.rag_node import (
    _with_chapter_course_evidence,
    _with_chapter_lecture_evidence,
)
from agent.rag.schemas import Citation, EvidenceItem, RagPackage


def _generic_package() -> RagPackage:
    evidence = EvidenceItem(
        source_file="安全题库.xlsx",
        chunk_id="generic:1",
        text="操作人员需要遵守安全规范。",
        score=0.2,
    )
    return RagPackage(
        query="数控车床基础认知",
        answer="通用检索结果",
        evidence=[evidence],
        citations=[Citation(source_file=evidence.source_file, chunk_id=evidence.chunk_id, label="安全题库")],
        confidence=0.2,
        warnings=[],
        next_action="need_more_evidence",
    )


class ChapterLectureRagTests(unittest.TestCase):
    def test_lecture_prioritizes_real_chapter_manual(self) -> None:
        package = _with_chapter_lecture_evidence(
            {
                "content_type": "lecture",
                "course_id": "cnc_lathe",
                "chapter_id": "1.1",
            },
            _generic_package(),
        )

        self.assertTrue(package.evidence)
        first = package.evidence[0]
        self.assertEqual(first.metadata.get("source_type"), "course_resource")
        self.assertEqual(first.metadata.get("chapter_id"), "1.1")
        self.assertIn("数控车床基础认知", first.text)
        self.assertGreater(package.confidence, 0.2)
        self.assertEqual(package.next_action, "use_as_grounded_context")
        self.assertTrue(any(item.chunk_id == "generic:1" for item in package.evidence))

    def test_non_lecture_package_is_unchanged(self) -> None:
        original = _generic_package()
        result = _with_chapter_lecture_evidence(
            {
                "content_type": "qa",
                "course_id": "cnc_lathe",
                "chapter_id": "1.1",
            },
            original,
        )

        self.assertIs(result, original)

    def test_quiz_prioritizes_the_same_real_chapter_manual(self) -> None:
        package = _with_chapter_course_evidence(
            {
                "content_type": "quiz",
                "course_id": "cnc_lathe",
                "chapter_id": "1.1",
            },
            _generic_package(),
        )

        self.assertTrue(package.evidence)
        first = package.evidence[0]
        self.assertEqual(first.metadata.get("source_type"), "course_resource")
        self.assertEqual(first.metadata.get("chapter_id"), "1.1")
        self.assertIn("数控车床基础认知", first.text)
        self.assertEqual(package.next_action, "use_as_grounded_context")


if __name__ == "__main__":
    unittest.main()
