"""Bob Manager — LightRAG graph-enhanced RAG service.

Routes all LLM calls through the orchestrator's LabDispatcher so they
benefit from load balancing, affinity, retries, and appear in the
LLM Activity dashboard.
"""

from __future__ import annotations

import logging
import os
import shutil

import numpy as np
from lightrag import LightRAG, QueryParam
from lightrag.kg.shared_storage import initialize_pipeline_status
from lightrag.utils import EmbeddingFunc
from sqlalchemy import select

from app.config import settings
from app.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


async def _bob_embedding_func(texts: list[str]) -> np.ndarray:
    """Bridge our EmbeddingService into LightRAG's expected interface."""
    vectors = await EmbeddingService.embed_texts(texts)
    return np.array(vectors, dtype=np.float32)


def _make_dispatcher_llm_func(model_identifier: str):
    """Create an LLM function that routes through LabDispatcher."""

    async def llm_func(
        prompt: str,
        system_prompt: str | None = None,
        history_messages: list[dict] | None = None,
        **kwargs,
    ) -> str:
        from app.database import async_session
        from app.services.lab_dispatcher import LabDispatcher

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history_messages:
            messages.extend(history_messages)
        messages.append({"role": "user", "content": prompt})

        async with async_session() as db:
            dispatcher = LabDispatcher(db)
            result = await dispatcher._call_with_loadbalance(
                model_identifier=model_identifier,
                messages=messages,
                temperature=0.0,
                max_tokens=4096,
                caller_name="LightRAG",
                caller_type="lightrag",
            )
        return result["content"]

    return llm_func


class LightRagService:
    """Manages per-collection LightRAG instances with file-based graph storage."""

    _instances: dict[str, LightRAG] = {}

    @classmethod
    async def _get_or_create(
        cls,
        collection_id: str,
        model_name: str,
        embedding_model: str = "all-MiniLM-L6-v2",
        embedding_dim: int = 384,
    ) -> LightRAG:
        if collection_id in cls._instances:
            return cls._instances[collection_id]

        working_dir = os.path.join(settings.lightrag_storage_path, collection_id)
        os.makedirs(working_dir, exist_ok=True)

        instance = LightRAG(
            working_dir=working_dir,
            llm_model_func=_make_dispatcher_llm_func(model_name),
            llm_model_name=model_name,
            embedding_func=EmbeddingFunc(
                embedding_dim=embedding_dim,
                func=_bob_embedding_func,
            ),
        )
        await instance.initialize_storages()
        await initialize_pipeline_status()

        cls._instances[collection_id] = instance
        return instance

    @classmethod
    async def ingest(
        cls,
        collection_id: str,
        model_name: str,
        text: str,
        embedding_model: str = "all-MiniLM-L6-v2",
        embedding_dim: int = 384,
    ) -> None:
        """Ingest raw text into a LightRAG collection (entity extraction + graph build)."""
        rag = await cls._get_or_create(
            collection_id, model_name,
            embedding_model, embedding_dim,
        )
        await rag.ainsert(text)

    @classmethod
    async def search(
        cls,
        collection_id: str,
        model_name: str,
        query: str,
        mode: str = "hybrid",
        embedding_model: str = "all-MiniLM-L6-v2",
        embedding_dim: int = 384,
    ) -> str:
        """Query a LightRAG collection. Returns the LightRAG response string."""
        rag = await cls._get_or_create(
            collection_id, model_name,
            embedding_model, embedding_dim,
        )
        result = await rag.aquery(
            query,
            param=QueryParam(mode=mode, only_need_context=True),
        )
        return result

    @classmethod
    async def delete_collection(cls, collection_id: str) -> None:
        """Remove a LightRAG collection's on-disk storage and cache."""
        working_dir = os.path.join(settings.lightrag_storage_path, collection_id)
        if os.path.exists(working_dir):
            shutil.rmtree(working_dir)
        cls._instances.pop(collection_id, None)

    @classmethod
    async def sweep_orphans(cls) -> int:
        """OP04 — remove on-disk LightRAG working dirs whose parent
        ``rag_collections`` row no longer exists.

        ``delete_collection`` is best-effort and the cleanup can race with
        a crash or a half-committed DB transaction, leaving directories
        with no owning row. Call from app startup so a long-running
        installation doesn't accumulate dead state under
        ``settings.lightrag_storage_path``. Returns the number of dirs
        removed.
        """
        from app.database import async_session
        from app.models.rag import RagCollection

        root = settings.lightrag_storage_path
        if not os.path.isdir(root):
            return 0
        try:
            entries = [e for e in os.listdir(root) if os.path.isdir(os.path.join(root, e))]
        except OSError:
            logger.exception("OP04: failed to list LightRAG storage root %s", root)
            return 0

        if not entries:
            return 0

        async with async_session() as db:
            result = await db.execute(select(RagCollection.id))
            live_ids = {str(row[0]) for row in result.all()}

        removed = 0
        for name in entries:
            if name in live_ids:
                continue
            path = os.path.join(root, name)
            try:
                shutil.rmtree(path)
                removed += 1
                logger.info("OP04: removed orphan LightRAG dir %s", path)
            except OSError:
                logger.exception("OP04: failed to remove orphan dir %s", path)
        return removed
