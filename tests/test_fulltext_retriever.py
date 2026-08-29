from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.rag.config import RagConfig
from agent.rag.simple_retriever import SimpleResourceRetriever, _score_text, _split_text


def _config(source_dir: Path, index_dir: Path) -> RagConfig:
    return RagConfig(
        source_dir=source_dir,
        index_dir=index_dir,
        manifest_dir=index_dir / "manifests",
        additional_source_dirs=(),
        top_k=8,
        min_score=0.01,
        max_pdf_pages=0,
    )


class FullTextRetrieverTests(unittest.TestCase):
    def test_source_tail_is_not_truncated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            tmp_path = Path(temporary)
            source_dir = tmp_path / "resource"
            source_dir.mkdir()
            marker = "G02和G03圆弧插补方向判定"
            (source_dir / "完整教材.txt").write_text("基础内容" * 7000 + marker, encoding="utf-8")

            chunks = SimpleResourceRetriever(_config(source_dir, tmp_path / "index"))._load_source_chunks([], [])

            self.assertTrue(any(marker in item.text for item in chunks))

    def test_page_label_is_preserved_in_chunks(self) -> None:
        chunks = _split_text(
            "G02为顺时针圆弧插补，G03为逆时针圆弧插补。",
            source_file="数控车编程与操作.pdf",
            file_type="pdf",
            page_label="47",
            metadata={"source_path": "resource/数控车编程与操作.pdf"},
        )

        self.assertEqual(chunks[0].page_label, "47")
        self.assertTrue(chunks[0].metadata["source_path"].endswith("数控车编程与操作.pdf"))

    def test_exact_technical_terms_rank_above_generic_text(self) -> None:
        queries = ["数控车床和数控铣床中G02和G03如何判定顺时针与逆时针"]
        relevant = "G02和G03用于圆弧插补。G02为顺时针，G03为逆时针，并根据加工平面判定。"
        generic = "数控机床包含车床和铣床，加工前应遵守安全操作规范。"

        self.assertGreater(
            _score_text(queries, relevant, "圆弧插补.pdf"),
            _score_text(queries, generic, "安全规范.pdf"),
        )


if __name__ == "__main__":
    unittest.main()
