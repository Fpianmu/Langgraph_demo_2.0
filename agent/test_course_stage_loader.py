from __future__ import annotations

import inspect
import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from agent.course_resources.repository import CourseResourceRepository  # noqa: E402
from agent.course_resources.stage_loader import load_course_stages, load_stage_prompt, next_stage_id  # noqa: E402
from agent.node.knowledge_generation import chapter_manifest_loader_node as chapter_manifest_module  # noqa: E402
from agent.node.learning_management import progress_advance_node as progress_module  # noqa: E402


COURSE_RESOURCE_ROOT = ROOT / "course_resources"


class CourseStageLoaderTests(unittest.TestCase):
    def test_load_stage_prompt_reads_course_resources_directly(self) -> None:
        stage = load_stage_prompt(
            "cnc_lathe",
            "1.1",
            path_id="standard",
            resource_root=COURSE_RESOURCE_ROOT,
        )

        self.assertEqual(stage["course_id"], "cnc_lathe")
        self.assertEqual(stage["path_id"], "standard")
        self.assertEqual(stage["chapter_id"], "1.1")
        self.assertEqual(stage["chapter_title"], "数控车床结构的认识")
        self.assertEqual(stage["next_chapter_id"], "1.2")
        self.assertIn("lecture", stage["required_material_types"])
        self.assertIn("quiz", stage["required_material_types"])

    def test_next_stage_id_uses_course_resources_path(self) -> None:
        self.assertEqual(
            next_stage_id(
                "cnc_lathe",
                "1.1",
                path_id="standard",
                resource_root=COURSE_RESOURCE_ROOT,
            ),
            "1.2",
        )

    def test_learning_stage_nodes_no_longer_reference_learning_stages_loader(self) -> None:
        progress_source = inspect.getsource(progress_module)
        chapter_source = inspect.getsource(chapter_manifest_module)

        self.assertNotIn("learning_stages.loader", progress_source)
        self.assertNotIn("learning_stages.loader", chapter_source)

    def test_load_course_stages_returns_sorted_chapters(self) -> None:
        course = load_course_stages(
            "cnc_lathe",
            path_id="standard",
            resource_root=COURSE_RESOURCE_ROOT,
        )

        self.assertEqual(course["course_id"], "cnc_lathe")
        self.assertGreater(len(course["chapters"]), 0)
        self.assertEqual(course["chapters"][0]["chapter_id"], "1.1")

    def test_course_resource_repository_loads_indexed_chapter_bundles(self) -> None:
        repo = CourseResourceRepository(COURSE_RESOURCE_ROOT)
        for chapter_id in ["1.1", "1.2", "1.3", "2.1", "3.1", "3.2", "3.3", "3.4", "3.5", "3.6", "3.7", "3.8"]:
            with self.subTest(chapter_id=chapter_id):
                bundle = repo.load_chapter_asset_bundle("cnc_lathe", chapter_id)
                self.assertEqual(bundle["chapter_id"], chapter_id)
                self.assertTrue(bundle["chapter_path"])


if __name__ == "__main__":
    unittest.main()
