"""RAG tools: rag_list_collections, rag_search, rag_ingest."""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.tool_executor import ToolExecutor

logger = logging.getLogger(__name__)

TOOLS = {
    "rag_list_collections": {
        "description": "List the RAG collections this lab can access, including descriptions and document counts.",
        "parameters": {},
    },
    "rag_search": {
        "description": "Search an accessible RAG collection using semantic similarity. For LightRAG collections, supports mode: local (vector), global (graph), hybrid (both). Use rag_list_collections first if needed.",
        "parameters": {
            "query": {"type": "string", "description": "Natural language search query", "required": True},
            "collection": {"type": "string", "description": "Collection name from rag_list_collections", "required": True},
            "top_k": {"type": "integer", "description": "Optional result count, default 5, max 20", "required": False},
            "mode": {"type": "string", "description": "Search mode for LightRAG collections: local, global, or hybrid (default)", "required": False},
            "filter": {"type": "object", "description": "Optional metadata filter object", "required": False},
            "score_threshold": {"type": "number", "description": "Optional minimum similarity score from 0 to 1", "required": False},
        },
    },
    "rag_ingest": {
        "description": "Ingest text content or a workspace file into a RAG collection this lab has write access to. Use rag_list_collections to find available collections.",
        "parameters": {
            "collection": {"type": "string", "description": "Collection name (from rag_list_collections)", "required": True},
            "filename": {"type": "string", "description": "Source label for the ingested document", "required": True},
            "source_file": {"type": "string", "description": "Path to workspace file to ingest (relative to lab workspace)", "required": False},
            "content": {"type": "string", "description": "Raw text content to ingest (alternative to source_file)", "required": False},
            "metadata": {"type": "object", "description": "Optional metadata tags (e.g. {\"source\": \"youtube\", \"video_id\": \"...\"})", "required": False},
        },
    },
}


async def rag_list_collections(executor: ToolExecutor, args: dict) -> dict:
    from app.services.rag_service import RagService

    collections = await RagService(executor.db).list_accessible_collections(executor.lab_id)
    if not collections:
        return {"success": True, "output": "No RAG collections are linked to this lab."}

    lines = []
    for collection in collections:
        mode_label = f" [{collection['rag_mode']}]" if collection.get('rag_mode', 'vector') != 'vector' else ""
        lines.append(
            f"- {collection['name']}{mode_label} ({collection['display_name']}): "
            f"{collection['document_count']} docs, {collection['chunk_count']} chunks. "
            f"{collection['description'] or 'No description.'}"
        )
    return {"success": True, "output": "\n".join(lines)}


async def rag_search(executor: ToolExecutor, args: dict) -> dict:
    from app.services.rag_service import RagService

    query = str(args.get("query", "")).strip()
    collection = str(args.get("collection", "")).strip()
    if not query or not collection:
        return {"success": False, "output": "rag_search requires 'query' and 'collection'."}

    metadata_filter = args.get("filter") or {}
    if isinstance(metadata_filter, str):
        try:
            metadata_filter = json.loads(metadata_filter)
        except json.JSONDecodeError:
            return {"success": False, "output": "rag_search filter must be valid JSON."}
    if not isinstance(metadata_filter, dict):
        return {"success": False, "output": "rag_search filter must be an object."}

    top_k = min(max(int(args.get("top_k", 5)), 1), 20)
    score_threshold = float(args.get("score_threshold", 0.3))
    mode = args.get("mode") or None

    try:
        results = await RagService(executor.db).search_for_lab(
            lab_id=executor.lab_id,
            collection_name=collection,
            query=query,
            top_k=top_k,
            score_threshold=score_threshold,
            metadata_filter=metadata_filter,
            mode=mode,
        )
    except PermissionError as exc:
        return {"success": False, "output": str(exc)}
    except ValueError as exc:
        return {"success": False, "output": str(exc)}

    if not results:
        return {"success": True, "output": f"No RAG matches found in '{collection}'."}

    lines = []
    for idx, item in enumerate(results, start=1):
        lines.append(
            f"{idx}. ({item['score']:.3f}) {item['source']} #{item['chunk']}\n{item['text']}"
        )
    return {"success": True, "output": "\n\n".join(lines)}


async def rag_ingest(executor: ToolExecutor, args: dict) -> dict:
    """Ingest text or a file into a RAG collection (requires write access)."""
    from app.services.rag_service import RagService

    collection_name = str(args.get("collection", "")).strip()
    filename = str(args.get("filename", "")).strip()
    source_file = str(args.get("source_file", "")).strip() if args.get("source_file") else None
    content = str(args.get("content", "")).strip() if args.get("content") else None
    metadata = args.get("metadata") or {}

    if not collection_name:
        return {"success": False, "output": "rag_ingest requires 'collection'."}
    if not filename:
        return {"success": False, "output": "rag_ingest requires 'filename'."}
    if not source_file and not content:
        return {"success": False, "output": "rag_ingest requires either 'source_file' or 'content'."}

    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            return {"success": False, "output": "metadata must be valid JSON."}

    rag_svc = RagService(executor.db)
    collection = await rag_svc.check_access(executor.lab_id, collection_name, permission="write")
    if not collection:
        return {"success": False, "output": f"Write access denied to collection '{collection_name}'."}

    if source_file:
        fpath = (executor.workspace / source_file).resolve()
        if not fpath.is_relative_to(executor.workspace.resolve()):
            return {"success": False, "output": "Path traversal denied."}
        if not fpath.is_file():
            fpath = (executor.workspace / "output" / source_file).resolve()
            if not fpath.is_relative_to(executor.workspace.resolve()) or not fpath.is_file():
                return {"success": False, "output": f"File not found: {source_file}"}
        try:
            content = fpath.read_text(errors="replace")
        except Exception as e:
            return {"success": False, "output": f"Failed to read file: {e}"}

    if not content or not content.strip():
        return {"success": False, "output": "No text content to ingest."}

    content_type = "text/plain"
    size_bytes = len(content.encode("utf-8"))

    try:
        document = await rag_svc.create_document(
            collection_id=collection.id,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            chunk_size=collection.default_chunk_size,
            chunk_overlap=collection.default_chunk_overlap,
            splitter=collection.default_splitter,
            metadata=metadata,
        )

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)

        try:
            document = await rag_svc.ingest_document(document.id, tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)

        if document.status == "failed":
            return {
                "success": False,
                "output": f"Ingestion failed: {document.error_message or 'unknown error'}",
            }

        chunk_count = document.chunk_count or 0
        return {
            "success": True,
            "output": (
                f"Ingested '{filename}' into collection '{collection_name}': "
                f"{chunk_count} chunks, {size_bytes} bytes."
            ),
        }
    except Exception as e:
        logger.exception("rag_ingest failed for lab %s", executor.lab_id)
        return {"success": False, "output": f"Ingestion error: {e}"}


HANDLERS = {
    "rag_list_collections": rag_list_collections,
    "rag_search": rag_search,
    "rag_ingest": rag_ingest,
}
