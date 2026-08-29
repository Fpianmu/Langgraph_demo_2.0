from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(override=True)


@dataclass(frozen=True)
class RagConfig:
    source_dir: Path
    index_dir: Path
    manifest_dir: Path
    additional_source_dirs: tuple[Path, ...] = ()
    top_k: int = 8
    min_score: float = 0.05
    # A value <= 0 means that every page is indexed.  The local corpus contains
    # long manuals whose useful chapters often start well after page 30.
    max_pdf_pages: int = 0
    deepseek_model: str = "deepseek-v4-flash"

    @classmethod
    def from_env(cls) -> "RagConfig":
        storage_root = Path(__file__).resolve().parent / "storage"
        local_kb_root = storage_root / "local_kb"
        source_dir = Path(os.getenv("RAG_SOURCE_DIR", local_kb_root / "source"))
        return cls(
            source_dir=source_dir,
            index_dir=Path(os.getenv("RAG_INDEX_DIR", local_kb_root / "indexes")),
            manifest_dir=Path(os.getenv("RAG_MANIFEST_DIR", local_kb_root / "manifests")),
            additional_source_dirs=_additional_source_dirs(source_dir),
            top_k=int(os.getenv("RAG_TOP_K", "8")),
            min_score=float(os.getenv("RAG_MIN_SCORE", "0.05")),
            max_pdf_pages=int(os.getenv("RAG_MAX_PDF_PAGES", "0")),
            deepseek_model=os.getenv("DEEPSEEK_LLM_MODEL", "deepseek-v4-flash"),
        )


def deepseek_api_key() -> str:
    return os.getenv("DEEPSEEK_API_KEY", "")


def _additional_source_dirs(source_dir: Path) -> tuple[Path, ...]:
    candidates = [
        *_parse_path_list(os.getenv("RAG_ADDITIONAL_SOURCE_DIRS", "")),
        Path(__file__).resolve().parents[3] / "resource",
        # When the backend lives in <Desktop>/多agent协作_demo/backend, the
        # user's existing knowledge corpus is the sibling <Desktop>/resource.
        Path(__file__).resolve().parents[4] / "resource",
    ]
    result: list[Path] = []
    seen = {source_dir.resolve() if source_dir.exists() else source_dir}
    for candidate in candidates:
        if not candidate.exists() or not candidate.is_dir():
            continue
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        result.append(candidate)
    return tuple(result)


def _parse_path_list(value: str) -> list[Path]:
    paths = []
    for item in value.split(os.pathsep):
        text = item.strip()
        if text:
            paths.append(Path(text))
    return paths
