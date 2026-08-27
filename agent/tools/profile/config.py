from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent.storage_layout import resolve_storage_root


@dataclass(frozen=True)
class ProfileConfig:
    storage_root: Path
    db_path: Path
    profile_dir: Path

    @classmethod
    def from_root(cls, storage_root: str | Path | None = None) -> "ProfileConfig":
        root = resolve_storage_root(storage_root)
        return cls(storage_root=root, db_path=root / "app.db", profile_dir=root / "users")
