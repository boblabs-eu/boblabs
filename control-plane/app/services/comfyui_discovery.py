"""Helpers for discovering model files from a ComfyUI server."""

import asyncio
from pathlib import Path

import httpx


_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=15.0, pool=30.0)

_EXCLUDED_FOLDERS = {
    "configs",
    "custom_nodes",
}

# ComfyUI ships placeholder files in every empty model folder
# (e.g. "put_checkpoints_here", "put_loras_here", "put_vae_here").
# These are not real models and must never be reported as available.
_MODEL_EXTENSIONS = {
    "safetensors", "ckpt", "pt", "pth", "bin", "gguf",
    "onnx", "sft", "vae", "yaml", "yml", "json",
}


def _is_placeholder_name(name: str) -> bool:
    lowered = name.lower()
    if lowered.startswith("put_") and lowered.endswith("_here"):
        return True
    if lowered in {"put_here", ".gitkeep", ".keep"}:
        return True
    return False


def _is_real_model_file(name: str) -> bool:
    if _is_placeholder_name(name):
        return False
    ext = Path(name).suffix.lstrip(".").lower()
    # Accept anything with a known model-ish extension; skip extension-less
    # placeholders. .yaml/.json are kept for things like configs/ but the
    # configs folder itself is excluded above.
    return bool(ext) and ext in _MODEL_EXTENSIONS


def _normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def _extract_model_name(item: object) -> str:
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for key in ("name", "filename", "path"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


async def list_comfyui_folders(base_url: str) -> list[str]:
    base = _normalize_base_url(base_url)
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(f"{base}/models")
        resp.raise_for_status()
        data = resp.json()

    if not isinstance(data, list):
        return []

    folders = []
    for item in data:
        if isinstance(item, str) and item.strip():
            folder = item.strip()
            if folder in _EXCLUDED_FOLDERS:
                continue
            folders.append(folder)
    return sorted(set(folders))


async def discover_comfyui_models(base_url: str) -> list[dict]:
    base = _normalize_base_url(base_url)
    folders = await list_comfyui_folders(base)
    if not folders:
        return []

    async def _fetch_folder_models(client: httpx.AsyncClient, folder: str) -> list[dict]:
        resp = await client.get(f"{base}/models/{folder}")
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            return []

        folder_models = []
        for item in data:
            name = _extract_model_name(item)
            if not name:
                continue
            if not _is_real_model_file(name):
                continue

            identifier = f"{folder}/{name}"
            extension = Path(name).suffix.lstrip(".").lower()
            folder_models.append(
                {
                    "name": name,
                    "model": identifier,
                    "identifier": identifier,
                    "size": 0,
                    "parameter_size": "",
                    "quantization": folder,
                    "family": folder,
                    "format": extension,
                    "capabilities": {
                        "folder": folder,
                        "format": extension,
                        "source": "comfyui",
                    },
                    "parameters": {
                        "folder": folder,
                        "extension": extension,
                    },
                }
            )
        return folder_models

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        results = await asyncio.gather(*[_fetch_folder_models(client, folder) for folder in folders])

    models = []
    seen_identifiers = set()
    for folder_models in results:
        for model in folder_models:
            identifier = model["identifier"]
            if identifier in seen_identifiers:
                continue
            seen_identifiers.add(identifier)
            models.append(model)

    return sorted(models, key=lambda model: (model["quantization"], model["name"].lower()))


async def comfyui_health_check(base_url: str) -> bool:
    base = _normalize_base_url(base_url)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            resp = await client.get(f"{base}/system_stats")
            if resp.status_code == 200:
                return True
            resp = await client.get(f"{base}/models")
            return resp.status_code == 200
    except Exception:
        return False