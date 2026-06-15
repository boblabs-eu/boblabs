"""Bob Manager Agent — Claude CLI model discovery collector.

Queries the local claude-cli wrapper (see claude-cli/ at the repo root —
Claude Code CLI behind an OpenAI-compatible HTTP front, deployed per GPU
server like Ollama) for its configured models and reports them to the
control plane. Identifiers arrive already namespaced ``claude-cli:<id>``
so they never collide with Anthropic API models in the shared model list.
"""

import logging

import httpx

logger = logging.getLogger(__name__)

CLAUDE_CLI_BASE_URL = "http://localhost:3021"


def get_claude_cli_models(base_url: str = CLAUDE_CLI_BASE_URL) -> list[dict]:
    """Query the claude-cli wrapper for available models (synchronous for
    collector pattern).

    Returns list of model info dicts, or empty list on failure.
    """
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{base_url}/v1/models")
            resp.raise_for_status()
            data = resp.json()

        models = []
        for m in data.get("data", []):
            model_id = m.get("id", "")
            if not model_id:
                continue
            models.append(
                {
                    "name": model_id,
                    "model": model_id,
                    "size": 0,
                    "parameter_size": "",
                    "quantization": "",
                    "family": "claude",
                    "format": "claude-cli",
                    "modified_at": "",
                }
            )
        return models

    except Exception as e:
        logger.debug("Claude CLI wrapper not available at %s: %s", base_url, e)
        return []
