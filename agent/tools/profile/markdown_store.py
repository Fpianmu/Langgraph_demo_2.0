from __future__ import annotations

import hashlib
from pathlib import Path

from agent.storage_layout import safe_segment


EDITABLE_PROFILE_SECTIONS = ("学习背景", "学习偏好", "教师备注")


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

    def snapshot(self, user_id: str) -> dict[str, str]:
        content = self.get_or_create(user_id)
        return {
            "content": content,
            "editable_content": _editable_content(content),
            "content_hash": _content_hash(content),
        }

    def update_editable_sections(
        self,
        user_id: str,
        *,
        editable_content: str,
        expected_hash: str,
    ) -> dict[str, str]:
        current = self.get_or_create(user_id)
        if expected_hash != _content_hash(current):
            raise RuntimeError("profile_markdown_conflict")

        replacements = _parse_editable_content(editable_content)
        updated = current
        for section in EDITABLE_PROFILE_SECTIONS:
            updated = _upsert_section(updated, section, replacements[section])
        self.path_for(user_id).write_text(updated, encoding="utf-8")
        return self.snapshot(user_id)


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _editable_content(document: str) -> str:
    blocks = []
    for section in EDITABLE_PROFILE_SECTIONS:
        blocks.append(f"## {section}\n{_section_body(document, section)}".rstrip())
    return "\n\n".join(blocks).rstrip() + "\n"


def _parse_editable_content(content: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current_section = ""
    current_lines: list[str] = []
    for line in content.splitlines():
        if line.startswith("## "):
            if current_section:
                sections[current_section] = "\n".join(current_lines).strip()
            elif any(item.strip() for item in current_lines):
                raise ValueError("editable_profile_preamble_not_allowed")
            current_section = line.removeprefix("## ").strip()
            if current_section not in EDITABLE_PROFILE_SECTIONS:
                raise ValueError(f"profile_section_not_editable:{current_section}")
            if current_section in sections:
                raise ValueError(f"duplicate_profile_section:{current_section}")
            current_lines = []
        else:
            current_lines.append(line)
    if current_section:
        sections[current_section] = "\n".join(current_lines).strip()

    missing = [section for section in EDITABLE_PROFILE_SECTIONS if section not in sections]
    if missing:
        raise ValueError(f"missing_editable_profile_sections:{','.join(missing)}")
    return sections


def _section_body(document: str, section: str) -> str:
    lines = document.rstrip().splitlines()
    marker = f"## {section}"
    try:
        start = lines.index(marker) + 1
    except ValueError:
        return ""
    end = next(
        (index for index in range(start, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    return "\n".join(lines[start:end]).strip()


def _upsert_section(document: str, section: str, body: str) -> str:
    lines = document.rstrip().splitlines()
    marker = f"## {section}"
    try:
        start = lines.index(marker)
    except ValueError:
        prefix = lines + ([""] if lines else [])
        suffix: list[str] = []
    else:
        end = next(
            (index for index in range(start + 1, len(lines)) if lines[index].startswith("## ")),
            len(lines),
        )
        prefix = lines[:start]
        suffix = lines[end:]

    block = [marker, *body.strip().splitlines()]
    updated_lines = [*prefix, *block]
    if suffix:
        updated_lines.extend(["", *suffix])
    return "\n".join(updated_lines).rstrip() + "\n"


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
