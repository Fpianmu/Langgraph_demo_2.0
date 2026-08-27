from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agent.storage_layout import ensure_within, resolve_storage_root, safe_segment
from agent.tools.operation_review_tools import operation_review_paths


def load_operation_submission(
    *,
    user_id: str,
    course_id: str,
    chapter_id: str,
    task_id: str,
    submission_id: str,
    storage_root: str | Path | None = None,
) -> dict[str, Any]:
    _safe_id_segment(user_id, "user_id")
    _safe_id_segment(course_id, "course_id")
    _safe_chapter_id(chapter_id)
    _safe_id_segment(task_id, "task_id")
    _safe_id_segment(submission_id, "submission_id")

    root = resolve_storage_root(storage_root)
    paths = operation_review_paths(
        user_id=user_id,
        chapter_id=chapter_id,
        task_id=task_id,
        submission_id=submission_id,
        storage_root=storage_root,
    )
    manifest_path = ensure_within(root, root / paths["manifest"])
    submission_path = ensure_within(root, root / paths["submission"])
    submission_folder = ensure_within(root, root / paths["submission_folder"])

    missing_files = [
        label
        for label, path in (
            ("manifest", manifest_path),
            ("submission", submission_path),
            ("measurement_params", _measurement_params_path(root, submission_folder, paths, {})),
        )
        if not path.exists()
    ]
    if missing_files:
        return _load_result("not_found", paths, missing_files=missing_files)

    manifest = _read_json_object(manifest_path)
    submission = _read_json_object(submission_path)
    measurement_path = _measurement_params_path(root, submission_folder, paths, submission)
    if not measurement_path.exists():
        return _load_result("not_found", paths, missing_files=["measurement_params"])
    measurement_params = _read_json_object(measurement_path)

    mismatches = _manifest_mismatches(
        manifest,
        course_id=course_id,
        chapter_id=chapter_id,
        task_id=task_id,
    )
    mismatches.extend(
        _submission_mismatches(
            submission,
            user_id=user_id,
            course_id=course_id,
            chapter_id=chapter_id,
            task_id=task_id,
            submission_id=submission_id,
        )
    )
    if mismatches:
        return _load_result("invalid", paths, mismatched_fields=mismatches)

    uploaded_images = _load_uploaded_images(
        root=root,
        submission_folder=submission_folder,
        uploaded_images_folder=ensure_within(root, root / paths["uploaded_images"]),
        submission=submission,
    )
    return {
        "operation_loaded_submission": submission,
        "operation_task_manifest": manifest,
        "operation_review_paths": paths,
        "uploaded_images": uploaded_images,
        "measurement_params": measurement_params,
        "operation_submission_load_result": {
            "status": "success",
            "missing_files": [],
            "mismatched_fields": [],
            "image_count": len(uploaded_images),
            "resolved_submission_folder": str(submission_folder),
        },
    }


def _load_result(
    status: str,
    paths: dict[str, str],
    *,
    missing_files: list[str] | None = None,
    mismatched_fields: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "operation_review_paths": paths,
        "operation_submission_load_result": {
            "status": status,
            "missing_files": missing_files or [],
            "mismatched_fields": mismatched_fields or [],
        },
    }


def _safe_id_segment(value: str, field: str) -> str:
    raw = str(value or "").strip()
    if not raw or safe_segment(raw) != raw:
        raise ValueError(f"unsafe {field}: {value}")
    return raw


def _safe_chapter_id(value: str) -> str:
    raw = str(value or "").strip()
    if not raw or ".." in raw or raw in {".", ".."} or not re.match(r"^[0-9A-Za-z_.-]+$", raw):
        raise ValueError(f"unsafe chapter_id: {value}")
    return raw


def _measurement_params_path(
    root: Path,
    submission_folder: Path,
    paths: dict[str, str],
    submission: dict[str, Any],
) -> Path:
    ref = str(submission.get("measurement_params_ref") or "").strip()
    if ref:
        return ensure_within(root, submission_folder / ref)
    return ensure_within(root, root / paths["measurement_params"])


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid json file: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"json file must contain an object: {path}")
    return value


def _manifest_mismatches(
    manifest: dict[str, Any],
    *,
    course_id: str,
    chapter_id: str,
    task_id: str,
) -> list[str]:
    return [
        f"manifest.{field}"
        for field, expected in (
            ("course_id", course_id),
            ("chapter_id", chapter_id),
            ("task_id", task_id),
        )
        if str(manifest.get(field) or "") != expected
    ]


def _submission_mismatches(
    submission: dict[str, Any],
    *,
    user_id: str,
    course_id: str,
    chapter_id: str,
    task_id: str,
    submission_id: str,
) -> list[str]:
    return [
        f"submission.{field}"
        for field, expected in (
            ("submission_id", submission_id),
            ("user_id", user_id),
            ("course_id", course_id),
            ("chapter_id", chapter_id),
            ("task_id", task_id),
        )
        if str(submission.get(field) or "") != expected
    ]


def _load_uploaded_images(
    *,
    root: Path,
    submission_folder: Path,
    uploaded_images_folder: Path,
    submission: dict[str, Any],
) -> list[dict[str, Any]]:
    if uploaded_images_folder.exists():
        stored_images = [
            {
                "name": path.stem,
                "path": str(path.resolve()),
                "source": "storage_upload",
            }
            for path in sorted(uploaded_images_folder.iterdir())
            if path.is_file()
        ]
        if stored_images:
            return stored_images

    uploaded_images = []
    for index, item in enumerate(submission.get("uploaded_images") or []):
        if not isinstance(item, dict):
            continue
        ref = str(item.get("path") or item.get("url") or "").strip()
        if not ref:
            continue
        image_path = _resolve_submission_image_ref(root, submission_folder, ref)
        uploaded_images.append(
            {
                "name": str(item.get("name") or image_path.stem or f"image_{index + 1}"),
                "path": str(image_path.resolve()),
                "source": "submission_ref",
            }
        )
    return uploaded_images


def _resolve_submission_image_ref(root: Path, submission_folder: Path, ref: str) -> Path:
    if ref.startswith("file://"):
        ref = ref[len("file://") :]
        if re.match(r"^/[A-Za-z]:", ref):
            ref = ref[1:]
    path = Path(ref)
    if not path.is_absolute():
        path = submission_folder / path
    return ensure_within(root, path)
