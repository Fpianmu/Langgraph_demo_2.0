from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.tools.profile.manager import ProfileManager
from agent.tools.profile.markdown_store import ProfileMarkdownStore


PROFILE_MARKDOWN = """# 用户画像：user_test

## 基础信息
- 昵称: 测试用户

## 学习背景
熟悉 C 语言。

## 能力评估
- 安全规范: 72

## 学习偏好
先讲结论。

## 教师备注
关注实际操作。

## 学习路径分配
- cnc_lathe: standard
"""


class ProfileMarkdownStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.store = ProfileMarkdownStore(Path(self.temporary_directory.name))
        path = self.store.path_for("user_test")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(PROFILE_MARKDOWN, encoding="utf-8")

    def test_snapshot_exposes_full_document_and_editable_sections(self) -> None:
        self.assertTrue(
            hasattr(self.store, "snapshot"),
            "ProfileMarkdownStore.snapshot must be implemented",
        )
        if not hasattr(self.store, "snapshot"):
            return

        snapshot = self.store.snapshot("user_test")

        self.assertEqual(snapshot["content"], PROFILE_MARKDOWN)
        self.assertEqual(
            snapshot["editable_content"],
            """## 学习背景
熟悉 C 语言。

## 学习偏好
先讲结论。

## 教师备注
关注实际操作。
""",
        )
        self.assertEqual(len(snapshot["content_hash"]), 64)

    def test_update_preserves_system_sections(self) -> None:
        self.assertTrue(
            hasattr(self.store, "update_editable_sections"),
            "ProfileMarkdownStore.update_editable_sections must be implemented",
        )
        if not hasattr(self.store, "update_editable_sections"):
            return

        snapshot = self.store.snapshot("user_test")
        updated = self.store.update_editable_sections(
            "user_test",
            editable_content="""## 学习背景
正在学习数控加工。

## 学习偏好
步骤化讲解，并解释原因。

## 教师备注
优先巩固安全规范。
""",
            expected_hash=snapshot["content_hash"],
        )

        self.assertIn("正在学习数控加工。", updated["content"])
        self.assertIn("- 安全规范: 72", updated["content"])
        self.assertIn("- cnc_lathe: standard", updated["content"])
        self.assertNotIn("熟悉 C 语言。", updated["content"])

    def test_update_rejects_stale_hash(self) -> None:
        self.assertTrue(
            hasattr(self.store, "update_editable_sections"),
            "ProfileMarkdownStore.update_editable_sections must be implemented",
        )
        if not hasattr(self.store, "update_editable_sections"):
            return

        with self.assertRaisesRegex(RuntimeError, "profile_markdown_conflict"):
            self.store.update_editable_sections(
                "user_test",
                editable_content="""## 学习背景
新的背景。

## 学习偏好
新的偏好。

## 教师备注
新的备注。
""",
                expected_hash="stale-hash",
            )


class ProfileMarkdownFeatureBoundaryTest(unittest.TestCase):
    def test_manager_exposes_profile_markdown_read_and_update(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            manager = ProfileManager(temporary_directory)
            self.assertTrue(
                hasattr(manager, "load_profile_markdown"),
                "ProfileManager.load_profile_markdown must be implemented",
            )
            self.assertTrue(
                hasattr(manager, "update_profile_markdown"),
                "ProfileManager.update_profile_markdown must be implemented",
            )

    def test_backend_and_frontend_expose_dedicated_markdown_routes(self) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        backend_source = (repository_root / "agent" / "api.py").read_text(encoding="utf-8")
        frontend_route = (
            repository_root
            / "web"
            / "app"
            / "api"
            / "profile"
            / "[userId]"
            / "markdown"
            / "route.ts"
        )

        self.assertIn('@app.get("/api/profile/{user_id}/markdown")', backend_source)
        self.assertIn('@app.put("/api/profile/{user_id}/markdown")', backend_source)
        self.assertTrue(frontend_route.is_file(), "Next.js profile Markdown route must exist")

    def test_user_center_uses_profile_markdown_editor_with_chinese_font_stack(self) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        client_path = repository_root / "web" / "lib" / "profile-markdown-client.ts"
        editor_path = repository_root / "web" / "components" / "ProfileMarkdownEditor.tsx"
        user_center_path = repository_root / "web" / "components" / "UserCenterView.tsx"
        css_path = repository_root / "web" / "app" / "globals.css"

        self.assertTrue(client_path.is_file(), "profile Markdown client must exist")
        self.assertTrue(editor_path.is_file(), "profile Markdown editor must exist")
        if not client_path.is_file() or not editor_path.is_file():
            return

        client_source = client_path.read_text(encoding="utf-8")
        editor_source = editor_path.read_text(encoding="utf-8")
        user_center_source = user_center_path.read_text(encoding="utf-8")
        css_source = css_path.read_text(encoding="utf-8")

        self.assertIn("loadProfileMarkdown", client_source)
        self.assertIn("saveProfileMarkdown", client_source)
        self.assertIn("profile.md 完整内容", editor_source)
        self.assertIn("自定义指令", editor_source)
        self.assertIn("<textarea", editor_source)
        self.assertIn("<ProfileMarkdownEditor", user_center_source)
        self.assertIn("Microsoft YaHei", css_source)
        self.assertIn(".profile-markdown-editor", css_source)


if __name__ == "__main__":
    unittest.main()
