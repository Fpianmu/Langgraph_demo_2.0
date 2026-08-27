from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

from agent.storage_layout import (
    ensure_within,
    resolve_doc_path,
    resolve_storage_root,
    safe_segment,
    storage_relative,
    user_root,
)
from agent.tools.learning_recommendation_tools import load_learning_recommendations
from agent.tools.profile_tools import load_profile_context, load_resource_difficulty_trace


def profile_payload(
    *,
    user_id: str,
    storage_root: str | Path | None = None,
    display_name: str | None = None,
    background_type: str | None = None,
) -> dict[str, Any]:
    context = load_profile_context(
        user_id=user_id,
        display_name=display_name,
        background_type=background_type,
        storage_root=storage_root,
    )
    root = resolve_storage_root(storage_root)
    payload = dict(context)
    payload["profile_md_url"] = storage_file_url(context["profile_md_ref"])
    payload["path_assignment_urls"] = _storage_urls_from_files(context.get("path_assignment_files", {}))
    payload["capability_assessment_urls"] = _storage_urls_from_files(context.get("capability_assessment_files", {}))
    payload["knowledge_gap_urls"] = _storage_urls_from_files(context.get("knowledge_gap_files", {}))
    payload["storage_root"] = str(root)
    return payload


def learning_progress_payload(*, user_id: str, storage_root: str | Path | None = None) -> dict[str, Any]:
    context = load_profile_context(user_id=user_id, storage_root=storage_root)
    return {
        "user_id": user_id,
        "learning_progress": context.get("learning_progress", []),
        "profile_md_ref": context.get("profile_md_ref"),
    }


def knowledge_gaps_payload(*, user_id: str, storage_root: str | Path | None = None) -> dict[str, Any]:
    context = load_profile_context(user_id=user_id, storage_root=storage_root)
    return {
        "user_id": user_id,
        "knowledge_gaps": context.get("knowledge_gaps", []),
        "knowledge_gap_summary": context.get("knowledge_gap_summary", {}),
        "knowledge_gap_files": context.get("knowledge_gap_files", {}),
    }


def scores_payload(*, user_id: str, storage_root: str | Path | None = None) -> dict[str, Any]:
    context = load_profile_context(user_id=user_id, storage_root=storage_root)
    capability = context.get("capability_assessment", {})
    return {
        "user_id": user_id,
        "scores": capability.get("score_map", {}),
        "capability_assessment": capability,
        "capability_profile_score": context.get("capability_profile_score", {}),
        "capability_assessment_summary": context.get("capability_assessment_summary", {}),
    }


def profile_score_payload(*, user_id: str, storage_root: str | Path | None = None) -> dict[str, Any]:
    context = load_profile_context(user_id=user_id, storage_root=storage_root)
    return {
        "user_id": user_id,
        "capability_profile_score": context.get("capability_profile_score", {}),
        "capability_assessment_summary": context.get("capability_assessment_summary", {}),
        "profile_md_ref": context.get("profile_md_ref"),
        "profile_md_url": storage_file_url(context.get("profile_md_ref")),
    }


def resource_difficulty_trace_payload(
    *,
    user_id: str,
    storage_root: str | Path | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    return load_resource_difficulty_trace(user_id=user_id, storage_root=storage_root, limit=limit)


def path_assignments_payload(*, user_id: str, storage_root: str | Path | None = None) -> dict[str, Any]:
    context = load_profile_context(user_id=user_id, storage_root=storage_root)
    return {
        "user_id": user_id,
        "path_assignments": context.get("path_assignments", []),
        "path_assignment_files": context.get("path_assignment_files", {}),
    }


def recommendations_payload(*, user_id: str, storage_root: str | Path | None = None) -> dict[str, Any]:
    payload = load_learning_recommendations(user_id=user_id, storage_root=storage_root)
    payload = dict(payload)
    payload["recommendation_urls"] = [
        storage_file_url(item.get("markdown_ref"))
        for item in payload.get("recommendations", [])
        if isinstance(item, dict) and item.get("markdown_ref")
    ]
    return payload


def list_artifacts_payload(*, user_id: str, storage_root: str | Path | None = None) -> dict[str, Any]:
    root = resolve_storage_root(storage_root)
    user_dir = user_root(root, user_id)
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    if user_dir.exists():
        for manifest_path in sorted(user_dir.rglob("manifest.json")):
            artifact_dir = manifest_path.parent
            artifact_id = artifact_dir.name
            if artifact_id in seen:
                continue
            seen.add(artifact_id)
            try:
                items.append(artifact_payload(user_id=user_id, artifact_id=artifact_id, storage_root=storage_root))
            except FileNotFoundError:
                continue
    return {"user_id": user_id, "artifacts": items}


def artifact_payload(
    *,
    user_id: str,
    artifact_id: str,
    storage_root: str | Path | None = None,
) -> dict[str, Any]:
    root = resolve_storage_root(storage_root)
    manifest_path = _find_artifact_manifest(root, user_id, artifact_id)
    artifact_dir = manifest_path.parent
    manifest = _read_json(manifest_path)
    files = manifest.get("files") if isinstance(manifest.get("files"), dict) else {}
    markdown_rel = _first_non_empty(
        files.get("markdown") if isinstance(files, dict) else None,
        manifest.get("markdown"),
        _guess_markdown_relative_path(root, artifact_dir, manifest),
    )
    assets_rel = _normalize_rel_paths(
        files.get("assets") if isinstance(files, dict) else None,
        manifest.get("assets"),
    )
    payload = {
        "user_id": user_id,
        "artifact_id": artifact_id,
        "artifact_type": str(manifest.get("artifact_type") or manifest.get("type") or artifact_dir.parent.name),
        "manifest": storage_relative(root, manifest_path),
        "manifest_url": storage_file_url(storage_relative(root, manifest_path)),
        "markdown": markdown_rel,
        "markdown_url": storage_file_url(markdown_rel),
        "assets": assets_rel,
        "asset_urls": [storage_file_url(item) for item in assets_rel],
        "manifest_data": manifest,
    }
    if "source_node" in manifest:
        payload["source_node"] = manifest["source_node"]
    return payload


def artifact_manifest_payload(
    *,
    user_id: str,
    artifact_id: str,
    storage_root: str | Path | None = None,
) -> dict[str, Any]:
    payload = artifact_payload(user_id=user_id, artifact_id=artifact_id, storage_root=storage_root)
    return payload["manifest_data"]


def artifact_markdown_text(
    *,
    user_id: str,
    artifact_id: str,
    storage_root: str | Path | None = None,
) -> str:
    root = resolve_storage_root(storage_root)
    manifest_path = _find_artifact_manifest(root, user_id, artifact_id)
    manifest = _read_json(manifest_path)
    files = manifest.get("files") if isinstance(manifest.get("files"), dict) else {}
    markdown_rel = _first_non_empty(
        files.get("markdown") if isinstance(files, dict) else None,
        manifest.get("markdown"),
        _guess_markdown_relative_path(root, manifest_path.parent, manifest),
    )
    markdown_path = resolve_doc_path(root, markdown_rel)
    if not markdown_path.exists():
        raise FileNotFoundError(markdown_rel)
    return markdown_path.read_text(encoding="utf-8")


def storage_file_url(storage_path: str | Path | None) -> str:
    if storage_path is None:
        return ""
    path = Path(storage_path)
    if path.is_absolute():
        try:
            path = path.resolve().relative_to(resolve_storage_root(None).resolve())
        except ValueError:
            pass
    text = str(path).replace("\\", "/").lstrip("/")
    return f"/api/storage/files/{quote(text, safe='/')}"


def read_storage_file_response(
    *,
    storage_root: str | Path | None,
    storage_path: str,
    request: Request,
    download: bool = False,
) -> Response:
    path = resolve_doc_path(storage_root, storage_path)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(storage_path)
    media_type, _encoding = mimetypes.guess_type(path.name)
    media_type = media_type or "application/octet-stream"
    if download:
        return FileResponse(path, filename=path.name, media_type=media_type)
    if media_type.startswith("text/") or media_type in {"application/json", "application/xml", "application/javascript"}:
        return Response(path.read_text(encoding="utf-8"), media_type=f"{media_type}; charset=utf-8")
    range_header = request.headers.get("range")
    if range_header and media_type.startswith(("video/", "audio/", "image/")):
        return _range_response(path, media_type, range_header)
    return FileResponse(path, media_type=media_type)


def _range_response(path: Path, media_type: str, range_header: str) -> Response:
    total_size = path.stat().st_size
    start, end = _parse_range_header(range_header, total_size)
    length = end - start + 1

    def iterator():
        with path.open("rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining > 0:
                chunk = handle.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Range": f"bytes {start}-{end}/{total_size}",
        "Content-Length": str(length),
    }
    return StreamingResponse(iterator(), status_code=206, media_type=media_type, headers=headers)


def _parse_range_header(range_header: str, total_size: int) -> tuple[int, int]:
    if not range_header.startswith("bytes="):
        raise HTTPException(status_code=416, detail="invalid range header")
    start_text, _, end_text = range_header.removeprefix("bytes=").partition("-")
    if not start_text and not end_text:
        raise HTTPException(status_code=416, detail="invalid range header")
    if start_text:
        start = int(start_text)
    else:
        suffix = int(end_text)
        if suffix <= 0:
            raise HTTPException(status_code=416, detail="invalid range header")
        start = max(total_size - suffix, 0)
    if end_text:
        end = int(end_text)
    else:
        end = total_size - 1
    if start < 0 or end < start or start >= total_size:
        raise HTTPException(status_code=416, detail="invalid range header")
    return start, min(end, total_size - 1)


def _storage_urls_from_files(files: Any) -> dict[str, str]:
    if not isinstance(files, dict):
        return {}
    return {str(key): storage_file_url(value) for key, value in files.items() if isinstance(value, str) and value}


def _find_artifact_manifest(root: Path, user_id: str, artifact_id: str) -> Path:
    user_dir = user_root(root, user_id)
    if not user_dir.exists():
        raise FileNotFoundError(user_id)
    for manifest_path in sorted(user_dir.rglob("manifest.json")):
        if manifest_path.parent.name == artifact_id:
            return manifest_path
    raise FileNotFoundError(artifact_id)


def _guess_markdown_relative_path(root: Path, artifact_dir: Path, manifest: dict[str, Any]) -> str:
    candidates = [
        manifest.get("markdown"),
        artifact_dir.name if artifact_dir.suffix == ".md" else None,
        next((item.name for item in artifact_dir.glob("*.md") if item.is_file()), None),
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            value = candidate.replace("\\", "/").lstrip("/")
            if value.endswith(".md"):
                if "/" in value:
                    return value
                return storage_relative(root, artifact_dir / value)
    artifact_type = str(manifest.get("artifact_type") or manifest.get("type") or "artifact")
    fallback = f"{artifact_type}.md"
    return storage_relative(root, artifact_dir / fallback)


def _normalize_rel_paths(*values: Any) -> list[str]:
    items: list[str] = []
    for value in values:
        if isinstance(value, str) and value.strip():
            items.append(value.replace("\\", "/").lstrip("/"))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    items.append(item.replace("\\", "/").lstrip("/"))
    # keep order but drop duplicates
    seen: set[str] = set()
    normalized: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return normalized


def _first_non_empty(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.replace("\\", "/").lstrip("/")
    return ""


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise FileNotFoundError(path)
    return data


def simulation_embed_payload(
    *,
    task_id: str,
    user_id: str = "",
    course_id: str = "cnc_lathe",
    chapter_id: str = "4.1",
    storage_root: str | Path | None = None,
    simulator_url: str | None = None,
    api_base_url: str | None = None,
) -> dict[str, Any]:
    root = resolve_storage_root(storage_root)
    return {
        "status": "success",
        "user_id": user_id,
        "course_id": course_id,
        "chapter_id": chapter_id,
        "task_id": task_id,
        "storage_root": str(root),
        "embed_mode": "iframe",
        "iframe_title": "CNC 车床仿真器",
        "simulator_url": simulator_url or "/simulator/#/embed/simulator",
        "api_base_url": api_base_url or "/simulator",
        "submission_endpoints": {
            "create": f"/api/simulation/{safe_segment(task_id)}/submissions",
            "read": f"/api/simulation/{safe_segment(task_id)}/submissions/{{submission_id}}",
        },
    }


def simulation_submission_payload(
    *,
    user_id: str,
    course_id: str,
    chapter_id: str,
    task_id: str,
    submission_id: str,
    storage_root: str | Path | None = None,
) -> dict[str, Any]:
    root = resolve_storage_root(storage_root)
    submission_folder = _simulation_submission_folder(
        root,
        user_id=user_id,
        chapter_id=chapter_id,
        task_id=task_id,
        submission_id=submission_id,
    )
    if not submission_folder.exists():
        raise FileNotFoundError(submission_id)
    manifest_path = ensure_within(root, submission_folder.parent.parent / "manifest.json")
    submission_path = ensure_within(root, submission_folder / "submission.json")
    source_code_path = ensure_within(root, submission_folder / "source_code.nc")

    files: list[dict[str, Any]] = []
    for path in sorted(item for item in submission_folder.rglob("*") if item.is_file()):
        relative = storage_relative(root, path)
        files.append(
            {
                "path": relative,
                "url": storage_file_url(relative),
                "name": path.name,
            }
        )

    return {
        "status": "success",
        "user_id": user_id,
        "course_id": course_id,
        "chapter_id": chapter_id,
        "task_id": task_id,
        "submission_id": submission_id,
        "storage_root": str(root),
        "task_manifest": storage_relative(root, manifest_path),
        "task_manifest_url": storage_file_url(storage_relative(root, manifest_path)),
        "manifest": storage_relative(root, manifest_path),
        "manifest_url": storage_file_url(storage_relative(root, manifest_path)),
        "submission": storage_relative(root, submission_path),
        "submission_url": storage_file_url(storage_relative(root, submission_path)),
        "source_code": storage_relative(root, source_code_path),
        "source_code_url": storage_file_url(storage_relative(root, source_code_path)),
        "files": files,
        "file_urls": [item["url"] for item in files],
    }


def _simulation_submission_folder(
    root: Path,
    *,
    user_id: str,
    chapter_id: str,
    task_id: str,
    submission_id: str,
) -> Path:
    return ensure_within(
        root,
        user_root(root, user_id)
        / "questions"
        / "path_generated"
        / _chapter_group(chapter_id)
        / _chapter_segment(chapter_id)
        / f"simulation_{safe_segment(task_id)}"
        / "submissions"
        / safe_segment(submission_id),
    )


def _chapter_group(chapter_id: str) -> str:
    prefix = str(chapter_id or "").split(".", 1)[0]
    return f"chapter_{int(prefix):02d}" if prefix.isdigit() else f"chapter_{safe_segment(prefix or 'unassigned')}"


def _chapter_segment(chapter_id: str) -> str:
    segment = "".join(char if char.isalnum() or char in {"_", "-", "."} else "_" for char in str(chapter_id))
    while ".." in segment:
        segment = segment.replace("..", "_")
    return segment or "unassigned"
