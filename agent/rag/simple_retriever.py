from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agent.rag.config import RagConfig
from agent.rag.schemas import Citation, EvidenceItem, RagPackage


SUPPORTED_EXTENSIONS = {".md", ".txt", ".docx", ".xlsx", ".pdf", ".pptx"}
MAX_CHARS_PER_FILE = 22000
CHUNK_CHARS = 900
CHUNK_OVERLAP = 120


class SimpleResourceRetriever:
    """Lightweight fallback retriever for local resource files.

    It first tries real docstore JSON when available. If the copied index files
    are Git LFS pointers, it searches the source files directly.
    """

    def __init__(self, config: RagConfig | None = None) -> None:
        self.config = config or RagConfig.from_env()

    def retrieve(self, queries: list[str]) -> RagPackage:
        clean_queries = [item.strip() for item in queries if item and item.strip()]
        query = "；".join(clean_queries)
        warnings: list[str] = []

        chunks = self._load_index_chunks(warnings)
        if not chunks:
            chunks = self._load_source_chunks(clean_queries, warnings)

        scored = []
        for item in chunks:
            score = _score_text(clean_queries, item.text, item.source_file)
            if score >= self.config.min_score:
                item.score = round(score, 4)
                scored.append(item)

        scored.sort(key=lambda item: item.score, reverse=True)
        evidence = scored[: self.config.top_k]
        citations = [_citation_for(item) for item in evidence]
        confidence = round(max((item.score for item in evidence), default=0.0), 4)
        next_action = "use_as_grounded_context" if evidence else "need_more_evidence"

        if not evidence:
            warnings.append("evidence_not_found")

        return RagPackage(
            query=query,
            answer=_extractive_answer(evidence),
            evidence=evidence,
            citations=citations,
            confidence=confidence,
            warnings=list(dict.fromkeys(warnings)),
            next_action=next_action,
        )

    def _load_index_chunks(self, warnings: list[str]) -> list[EvidenceItem]:
        docstore_path = self.config.index_dir / "docstore.json"
        if not docstore_path.exists():
            warnings.append(f"index_docstore_missing:{docstore_path}")
            return []

        text = docstore_path.read_text(encoding="utf-8", errors="ignore")
        if text.startswith("version https://git-lfs.github.com/spec"):
            warnings.append("index_docstore_is_lfs_pointer")
            return []

        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            warnings.append("index_docstore_json_invalid")
            return []

        chunks = []
        for index, raw_node in enumerate(_iter_docstore_nodes(value), start=1):
            node = _node_payload(raw_node)
            node_text = _node_text(node)
            if not node_text:
                continue
            metadata = node.get("metadata") if isinstance(node, dict) else {}
            metadata = metadata if isinstance(metadata, dict) else {}
            source_file = str(
                metadata.get("source_file")
                or metadata.get("file_name")
                or metadata.get("source_doc")
                or "docstore"
            )
            chunks.append(
                EvidenceItem(
                    source_file=source_file,
                    chunk_id=str(node.get("id_") or node.get("node_id") or f"docstore_{index}"),
                    text=node_text,
                    file_type=str(metadata.get("file_type") or ""),
                    page_label=_optional_str(metadata.get("page_label") or metadata.get("page")),
                    metadata=metadata,
                )
            )
        return chunks

    def _load_source_chunks(self, queries: list[str], warnings: list[str]) -> list[EvidenceItem]:
        files: list[Path] = []
        for source_dir in _source_dirs(self.config):
            if not source_dir.exists():
                warnings.append(f"source_dir_missing:{source_dir}")
                continue
            files.extend(
                item
                for item in source_dir.iterdir()
                if item.is_file() and item.suffix.lower() in SUPPORTED_EXTENSIONS
            )
        files.sort(key=lambda path: _score_filename(queries, path.name), reverse=True)

        chunks: list[EvidenceItem] = []
        for path in files:
            try:
                text = _read_source_text(path, max_pdf_pages=self.config.max_pdf_pages)
            except Exception as exc:
                warnings.append(f"source_read_failed:{path.name}:{type(exc).__name__}")
                continue
            text = text[:MAX_CHARS_PER_FILE]
            chunks.extend(_split_text(text, source_file=path.name, file_type=path.suffix.lower().lstrip(".")))
        return chunks


def _source_dirs(config: RagConfig) -> list[Path]:
    dirs: list[Path] = []
    seen: set[Path] = set()
    for source_dir in [config.source_dir, *getattr(config, "additional_source_dirs", ())]:
        key = source_dir.resolve() if source_dir.exists() else source_dir
        if key in seen:
            continue
        seen.add(key)
        dirs.append(source_dir)
    return dirs


def _iter_docstore_nodes(value: Any):
    if isinstance(value, dict):
        for key in ("docstore/data", "data", "docs", "nodes"):
            nested = value.get(key)
            if isinstance(nested, dict):
                yield from nested.values()
            elif isinstance(nested, list):
                yield from nested
        for item in value.values():
            if isinstance(item, dict) and ("text" in item or "metadata" in item):
                yield item


def _node_payload(node: Any) -> dict[str, Any]:
    if not isinstance(node, dict):
        return {}
    wrapped = node.get("__data__")
    if isinstance(wrapped, dict):
        return wrapped
    return node


def _node_text(node: Any) -> str:
    if not isinstance(node, dict):
        return ""
    for key in ("text", "content", "text_resource"):
        value = node.get(key)
        if isinstance(value, str):
            return _clean_text(value)
        if isinstance(value, dict) and isinstance(value.get("text"), str):
            return _clean_text(value["text"])
    return ""


def _read_source_text(path: Path, *, max_pdf_pages: int) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".docx":
        from docx import Document

        document = Document(str(path))
        return "\n".join(paragraph.text for paragraph in document.paragraphs)
    if suffix == ".xlsx":
        from openpyxl import load_workbook

        workbook = load_workbook(str(path), read_only=True, data_only=True)
        rows = []
        for sheet in workbook.worksheets:
            for row in sheet.iter_rows(values_only=True):
                values = [str(cell) for cell in row if cell is not None]
                if values:
                    rows.append(f"{sheet.title}: " + " | ".join(values))
        return "\n".join(rows)
    if suffix == ".pdf":
        return _read_pdf_text(path, max_pages=max_pdf_pages)
    if suffix == ".pptx":
        return _read_pptx_text(path)
    return ""


def _read_pdf_text(path: Path, *, max_pages: int) -> str:
    try:
        import fitz

        with fitz.open(path) as document:
            pages = [document[index].get_text("text") for index in range(min(document.page_count, max_pages))]
        return "\n".join(pages)
    except ModuleNotFoundError:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages[:max_pages]]
    return "\n".join(pages)


def _read_pptx_text(path: Path) -> str:
    from pptx import Presentation

    presentation = Presentation(str(path))
    parts: list[str] = []
    for slide_index, slide in enumerate(presentation.slides, start=1):
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False):
                text = shape.text_frame.text.strip()
                if text:
                    parts.append(f"slide {slide_index}: {text}")
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    values = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                    if values:
                        parts.append(f"slide {slide_index}: " + " | ".join(values))
    return "\n".join(parts)


def _split_text(text: str, *, source_file: str, file_type: str) -> list[EvidenceItem]:
    cleaned = _clean_text(text)
    if not cleaned:
        return []
    chunks = []
    start = 0
    index = 1
    while start < len(cleaned):
        end = min(start + CHUNK_CHARS, len(cleaned))
        chunk = cleaned[start:end].strip()
        if chunk:
            chunks.append(
                EvidenceItem(
                    source_file=source_file,
                    chunk_id=f"{Path(source_file).stem}_{index:04d}",
                    text=chunk,
                    file_type=file_type,
                )
            )
        if end == len(cleaned):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
        index += 1
    return chunks


def _score_text(queries: list[str], text: str, source_file: str) -> float:
    haystack = f"{source_file}\n{text}".lower()
    tokens = _query_tokens(" ".join(queries))
    if not tokens:
        return 0.0
    hits = sum(1 for token in tokens if token.lower() in haystack)
    char_hits = len(_search_chars("".join(queries)) & _search_chars(haystack))
    return min(1.0, hits / len(tokens) * 0.75 + min(char_hits / 80, 0.25))


def _score_filename(queries: list[str], filename: str) -> float:
    name = filename.lower()
    tokens = _query_tokens(" ".join(queries))
    return sum(1 for token in tokens if token.lower() in name)


def _query_tokens(text: str) -> list[str]:
    english = re.findall(r"[A-Za-z0-9_]{2,}", text)
    chinese = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    words = english + chinese
    expanded = []
    for word in words:
        expanded.append(word)
        if len(word) > 4 and re.search(r"[\u4e00-\u9fff]", word):
            expanded.extend(word[index : index + 2] for index in range(0, len(word) - 1))
    return list(dict.fromkeys(expanded))


def _search_chars(text: str) -> set[str]:
    return {char for char in text if "\u4e00" <= char <= "\u9fff"}


def _citation_for(item: EvidenceItem) -> Citation:
    label = item.source_file
    if item.page_label:
        label = f"{label}，第 {item.page_label} 页"
    return Citation(source_file=item.source_file, chunk_id=item.chunk_id, label=label)


def _extractive_answer(evidence: list[EvidenceItem]) -> str:
    if not evidence:
        return ""
    return "\n".join(f"[{index}] {item.text[:220]}" for index, item in enumerate(evidence, start=1))


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None
