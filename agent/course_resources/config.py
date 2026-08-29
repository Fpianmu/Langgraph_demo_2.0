from __future__ import annotations

from pathlib import Path


COURSE_RESOURCES_DIR = "course_resources"


def resolve_course_resource_root(resource_root: str | Path | None = None) -> Path:
    if resource_root is None:
        return Path(__file__).resolve().parent

    root = Path(resource_root).expanduser().resolve()
    if root.name != COURSE_RESOURCES_DIR:
        root = root / COURSE_RESOURCES_DIR
    return root
