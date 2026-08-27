from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent.storage_layout import resolve_storage_root


@dataclass(frozen=True)
class ArchiveConfig:
    storage_root: Path
    db_path: Path
    artifact_dir: Path

    @classmethod
    def from_root(cls, storage_root: str | Path | None = None) -> "ArchiveConfig":
        root = resolve_storage_root(storage_root)
        return cls(storage_root=root, db_path=root / "app.db", artifact_dir=root)
