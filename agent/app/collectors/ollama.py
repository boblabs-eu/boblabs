"""Bob Manager Agent — Ollama model discovery collector.

Queries a local Ollama instance for available models and reports them
to the control plane.
"""

import logging

import httpx

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = "http://localhost:11434"


def get_ollama_models(base_url: str = OLLAMA_BASE_URL) -> list[dict]:
    """Query Ollama for available models (synchronous for collector pattern).

    Returns list of model info dicts, or empty list on failure.
    """
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{base_url}/api/tags")
            resp.raise_for_status()
            data = resp.json()

        models = []
        for m in data.get("models", []):
            details = m.get("details", {})
            models.append(
                {
                    "name": m.get("name", ""),
                    "model": m.get("model", m.get("name", "")),
                    "size": m.get("size", 0),
                    "parameter_size": details.get("parameter_size", ""),
                    "quantization": details.get("quantization_level", ""),
                    "family": details.get("family", ""),
                    "format": details.get("format", ""),
                    "modified_at": m.get("modified_at", ""),
                }
            )
        return models

    except Exception as e:
        logger.debug("Ollama not available at %s: %s", base_url, e)
        return []


async def get_ollama_models_async(
    base_url: str = OLLAMA_BASE_URL,
) -> list[dict]:
    """Async version of model discovery."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base_url}/api/tags")
            resp.raise_for_status()
            data = resp.json()

        models = []
        for m in data.get("models", []):
            details = m.get("details", {})
            models.append(
                {
                    "name": m.get("name", ""),
                    "model": m.get("model", m.get("name", "")),
                    "size": m.get("size", 0),
                    "parameter_size": details.get("parameter_size", ""),
                    "quantization": details.get("quantization_level", ""),
                    "family": details.get("family", ""),
                    "format": details.get("format", ""),
                    "modified_at": m.get("modified_at", ""),
                }
            )
        return models

    except Exception as e:
        logger.debug("Ollama not available at %s: %s", base_url, e)
        return []
