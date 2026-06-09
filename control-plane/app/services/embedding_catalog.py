"""Bob Manager - Supported embedding models for RAG."""

from __future__ import annotations

SUPPORTED_EMBEDDING_MODELS: dict[str, dict[str, int | str]] = {
    "all-MiniLM-L6-v2": {
        "runtime_name": "all-MiniLM-L6-v2",
        "dimension": 384,
    },
    "bge-base-en-v1.5": {
        "runtime_name": "BAAI/bge-base-en-v1.5",
        "dimension": 768,
    },
    "bge-large-en-v1.5": {
        "runtime_name": "BAAI/bge-large-en-v1.5",
        "dimension": 1024,
    },
}

_EMBEDDING_MODEL_ALIASES = {
    "all-MiniLM-L6-v2": "all-MiniLM-L6-v2",
    "sentence-transformers/all-MiniLM-L6-v2": "all-MiniLM-L6-v2",
    "bge-base-en-v1.5": "bge-base-en-v1.5",
    "BAAI/bge-base-en-v1.5": "bge-base-en-v1.5",
    "bge-large-en-v1.5": "bge-large-en-v1.5",
    "BAAI/bge-large-en-v1.5": "bge-large-en-v1.5",
}


def normalize_embedding_model(model_name: str) -> str:
    canonical_name = _EMBEDDING_MODEL_ALIASES.get(model_name)
    if canonical_name:
        return canonical_name
    supported = ", ".join(SUPPORTED_EMBEDDING_MODELS)
    raise ValueError(f"Unsupported embedding model '{model_name}'. Supported models: {supported}.")


def get_embedding_dimension(model_name: str) -> int:
    canonical_name = normalize_embedding_model(model_name)
    return int(SUPPORTED_EMBEDDING_MODELS[canonical_name]["dimension"])


def get_runtime_embedding_model(model_name: str) -> str:
    canonical_name = normalize_embedding_model(model_name)
    return str(SUPPORTED_EMBEDDING_MODELS[canonical_name]["runtime_name"])
