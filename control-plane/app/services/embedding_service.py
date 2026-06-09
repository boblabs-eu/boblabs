"""Bob Manager — Embedding service for RAG."""

from __future__ import annotations

import asyncio
import threading
from typing import Sequence

from app.config import settings
from app.services.embedding_catalog import get_runtime_embedding_model, normalize_embedding_model


class EmbeddingService:
    """Lazy singleton wrapper around SentenceTransformer."""

    _models: dict[str, object] = {}
    _lock = threading.Lock()

    @classmethod
    def _load_model(cls, model_name: str):
        canonical_name = normalize_embedding_model(model_name)
        with cls._lock:
            model = cls._models.get(canonical_name)
            if model is None:
                from sentence_transformers import SentenceTransformer

                model = SentenceTransformer(get_runtime_embedding_model(canonical_name))
                cls._models[canonical_name] = model
        return model

    @classmethod
    async def embed_texts(
        cls, texts: Sequence[str], model_name: str | None = None
    ) -> list[list[float]]:
        if not texts:
            return []

        requested_model = model_name or settings.embedding_model
        model = await asyncio.to_thread(cls._load_model, requested_model)
        embeddings = await asyncio.to_thread(
            model.encode,
            list(texts),
            normalize_embeddings=True,
            batch_size=settings.embedding_batch_size,
            show_progress_bar=False,
        )
        if hasattr(embeddings, "tolist"):
            return embeddings.tolist()
        return [list(row) for row in embeddings]

    @classmethod
    async def embed_query(cls, query: str, model_name: str | None = None) -> list[float]:
        vectors = await cls.embed_texts([query], model_name=model_name)
        return vectors[0]
