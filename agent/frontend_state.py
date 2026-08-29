from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.api_storage import profile_payload
from agent.storage_layout import resolve_storage_root, user_root


def load_frontend_workspace_state(
    *,
    user_id: str,
    storage_root: str | Path | None = None,
) -> dict[str, Any]:
    """Return the v2 learner profile together with ZLink's UI snapshot.

    The graph-owned profile and assessment files remain authoritative.  Chat,
    quiz, lecture and UI state are stored separately so reopening the browser
    does not lose the learner's local workspace.
    """
    base = profile_payload(user_id=user_id, storage_root=storage_root)
    saved = _read_json(_state_path(user_id=user_id, storage_root=storage_root))
    return {
        **base,
        "profile": saved.get("profile", {}),
        "frontend_state": saved.get("frontend_state", {}),
        "client_revision": int(saved.get("client_revision") or 0),
        "state_updated_at": saved.get("state_updated_at"),
    }


def save_frontend_workspace_state(
    *,
    user_id: str,
    payload: dict[str, Any],
    storage_root: str | Path | None = None,
) -> dict[str, Any]:
    path = _state_path(user_id=user_id, storage_root=storage_root)
    current = _read_json(path)
    current_revision = int(current.get("client_revision") or 0)
    incoming_revision = int(payload.get("client_revision") or current_revision + 1)

    # An older browser tab must not overwrite a newer completed interaction.
    if incoming_revision < current_revision:
        return load_frontend_workspace_state(user_id=user_id, storage_root=storage_root)

    document = {
        "state_version": 1,
        "user_id": user_id,
        "profile": payload.get("profile") if isinstance(payload.get("profile"), dict) else current.get("profile", {}),
        "frontend_state": payload.get("frontend_state")
        if isinstance(payload.get("frontend_state"), dict)
        else current.get("frontend_state", {}),
        "client_revision": incoming_revision,
        "state_updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json_atomic(path, document)
    return load_frontend_workspace_state(user_id=user_id, storage_root=storage_root)


def _state_path(*, user_id: str, storage_root: str | Path | None) -> Path:
    root = resolve_storage_root(storage_root)
    return user_root(root, user_id) / "frontend" / "workspace_state.json"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)
