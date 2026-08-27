from __future__ import annotations

from pathlib import Path

from agent.storage_layout import safe_segment


class ProfileMarkdownStore:
    def __init__(self, profile_dir: Path) -> None:
        self.profile_dir = profile_dir
        self.profile_dir.mkdir(parents=True, exist_ok=True)

    def get_or_create(self, user_id: str, *, display_name: str | None = None, background_type: str | None = None) -> str:
        path = self.path_for(user_id)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_default_markdown(user_id, display_name, background_type), encoding="utf-8")
        return path.read_text(encoding="utf-8")

    def apply_section_patch(self, user_id: str, section: str, content: str) -> str:
        current = self.get_or_create(user_id)
        marker = f"## {section.strip()}"
        patch_text = content.strip()
        if not patch_text:
            return current
        if marker in current:
            updated = current.rstrip() + f"\n\n{marker}\n{patch_text}\n"
        else:
            updated = current.rstrip() + f"\n\n{marker}\n{patch_text}\n"
        self.path_for(user_id).write_text(updated, encoding="utf-8")
        return updated

    def upsert_section(self, user_id: str, section: str, content: str) -> str:
        current = self.get_or_create(user_id)
        marker = f"## {section.strip()}"
        block = [marker, content.strip()]
        lines = current.rstrip().splitlines()
        try:
            start = lines.index(marker)
        except ValueError:
            updated_lines = lines + [""] + block
        else:
            end = len(lines)
            for index in range(start + 1, len(lines)):
                if lines[index].startswith("## "):
                    end = index
                    break
            prefix = lines[:start]
            suffix = lines[end:]
            updated_lines = prefix + block
            if suffix:
                updated_lines += [""] + suffix
        updated = "\n".join(updated_lines).rstrip() + "\n"
        self.path_for(user_id).write_text(updated, encoding="utf-8")
        return updated

    def path_for(self, user_id: str) -> Path:
        return self.profile_dir / safe_segment(user_id) / "profile" / "profile.md"


def _default_markdown(user_id: str, display_name: str | None, background_type: str | None) -> str:
    return "\n".join(
        [
            f"# 用户画像：{user_id}",
            "",
            "## 基础信息",
            f"- 昵称: {display_name or user_id}",
            f"- 背景类型: {background_type or 'unknown'}",
            "",
            "## 学习背景",
            "暂无。",
            "",
            "## 学习偏好",
            "暂无。",
            "",
            "## 当前薄弱点",
            "暂无。",
            "",
            "## 教师备注",
            "暂无。",
            "",
        ]
    )
