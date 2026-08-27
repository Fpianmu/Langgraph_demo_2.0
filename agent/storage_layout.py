from __future__ import annotations

import re
import shutil
from pathlib import Path


DOC_DIR = "doc"
LEGACY_A_RATING_DOCS_DIR = "A_rating_docs"
_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_LEGACY_STORAGE_DOC_ROOT = Path(__file__).resolve().parent / "storage" / DOC_DIR
_RUNTIME_STORAGE_DOC_ROOT = _PACKAGE_ROOT / "web" / "runtime" / DOC_DIR


def resolve_storage_root(storage_root: str | Path | None = None) -> Path:
    if storage_root is None:
        root = _RUNTIME_STORAGE_DOC_ROOT
    else:
        root = Path(storage_root).expanduser()
        if root.name == LEGACY_A_RATING_DOCS_DIR:
            root = root.parent / DOC_DIR
        elif root.name != DOC_DIR:
            root = root / DOC_DIR
    return root.resolve()


def safe_segment(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in str(value or ""))


def ensure_within(root: str | Path, path: str | Path) -> Path:
    root_path = Path(root).expanduser().resolve()
    target = Path(path).expanduser().resolve()
    try:
        target.relative_to(root_path)
    except ValueError as exc:
        raise ValueError(f"path escapes root: {target}") from exc
    return target


def user_root(root: str | Path, user_id: str) -> Path:
    return ensure_within(root, Path(root) / "users" / safe_segment(user_id))


def resolve_doc_path(storage_root: str | Path | None, storage_path: str | Path) -> Path:
    root = resolve_storage_root(storage_root)
    candidate = Path(str(storage_path).replace("\\", "/").lstrip("/"))
    if candidate.parts and candidate.parts[0].lower() == DOC_DIR:
        candidate = Path(*candidate.parts[1:])
    if candidate.is_absolute():
        raise ValueError("path escapes root: absolute paths are not allowed")
    if any(part == ".." for part in candidate.parts):
        raise ValueError("path escapes root: parent traversal is not allowed")
    return ensure_within(root, root / candidate)


def storage_relative(root: str | Path, path: str | Path) -> str:
    root_path = Path(root).expanduser().resolve()
    target_path = Path(path).expanduser().resolve()
    return str(target_path.relative_to(root_path)).replace("\\", "/")


def legacy_storage_root_for(storage_root: Path) -> Path:
    return storage_root.parent if storage_root.name in {DOC_DIR, LEGACY_A_RATING_DOCS_DIR} else storage_root


def migrate_legacy_storage(storage_root: Path) -> None:
    legacy_root = _LEGACY_STORAGE_DOC_ROOT
    if legacy_root.resolve() == storage_root.resolve():
        return
    storage_root.mkdir(parents=True, exist_ok=True)
    legacy_docs_root = legacy_root / LEGACY_A_RATING_DOCS_DIR
    if legacy_docs_root != storage_root:
        _copy_tree_children_if_missing(legacy_docs_root, storage_root)
    _copy_file_if_missing(legacy_root / "app.db", storage_root / "app.db")
    _copy_profile_markdown_files(legacy_root / "profiles", storage_root)
    _copy_tree_children_if_missing(legacy_root / "artifacts", storage_root / "legacy_artifacts")


def _copy_profile_markdown_files(legacy_profile_dir: Path, storage_root: Path) -> None:
    if not legacy_profile_dir.exists():
        return
    for profile_path in legacy_profile_dir.glob("*.md"):
        target = user_root(storage_root, profile_path.stem) / "profile" / "profile.md"
        _copy_file_if_missing(profile_path, target)


def _copy_tree_children_if_missing(source: Path, target: Path) -> None:
    if not source.exists():
        return
    target.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        destination = target / child.name
        if destination.exists():
            continue
        if child.is_dir():
            shutil.copytree(child, destination)
        elif child.is_file():
            _copy_file_if_missing(child, destination)


def _copy_file_if_missing(source: Path, target: Path) -> None:
    if source.exists() and source.is_file() and not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
