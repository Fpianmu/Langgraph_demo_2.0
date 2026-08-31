from __future__ import annotations

import json
from datetime import datetime, timezone

from agent.rag.config import RagConfig
from agent.rag.simple_retriever import SimpleResourceRetriever


def main() -> int:
    """Build the lightweight document index supported by backend v2.

    This creates a persistent full-text chunk docstore for the second-version
    backend. Ranking remains lexical; no embedding metadata is written.
    """
    config = RagConfig.from_env()
    warnings: list[str] = []
    chunks = SimpleResourceRetriever(config)._load_source_chunks([], warnings)
    config.index_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "index_version": "zlink-v2-fulltext-2",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "retrieval_mode": "lexical_fulltext",
        "source_file_count": len({item.metadata.get("source_path", item.source_file) for item in chunks}),
        "chunk_count": len(chunks),
        "nodes": [
            {
                "id_": item.chunk_id,
                "text": item.text,
                "metadata": {
                    **item.metadata,
                    "source_file": item.source_file,
                    "file_type": item.file_type,
                    "page_label": item.page_label,
                },
            }
            for item in chunks
        ],
    }
    target = config.index_dir / "docstore.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(target)
    print(f"Indexed {len(chunks)} chunks into {target}")
    for warning in warnings:
        print(f"WARNING: {warning}")
    return 0 if chunks else 1


if __name__ == "__main__":
    raise SystemExit(main())
