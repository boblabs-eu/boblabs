"""Bob Manager Agent — GPU services (MusicGen, Bark, RVC, CoquiTTS) discovery collector.

Probes local FastAPI GPU services and reports availability.
Each service exposes GET /health for liveness checks.
"""

import logging

import httpx

logger = logging.getLogger(__name__)

MUSICGEN_DEFAULT_URL = "http://localhost:3014"
BARK_DEFAULT_URL = "http://localhost:3015"
RVC_DEFAULT_URL = "http://localhost:3016"
COQUI_TTS_DEFAULT_URL = "http://localhost:3017"
STT_DEFAULT_URL = "http://localhost:7865"
LTX_VIDEO_DEFAULT_URL = "http://localhost:3018"
WAN_VIDEO_DEFAULT_URL = "http://localhost:3019"
COMFYUI_DEFAULT_URL = "http://localhost:8188"


def _probe_service(
    base_url: str, name: str, family: str = "audio", fmt: str = "neural"
) -> list[dict]:
    """Probe a GPU service's /health endpoint and return model info."""
    try:
        with httpx.Client(timeout=3.0) as client:
            resp = client.get(f"{base_url}/health")
            if resp.status_code == 200:
                data = resp.json()
                return [
                    {
                        "name": name,
                        "model": data.get("model", name),
                        "size": 0,
                        "parameter_size": "",
                        "quantization": fmt,
                        "family": family,
                        "format": fmt,
                        "gpu": data.get("gpu", ""),
                        "vram_used_mb": data.get("vram_used_mb", 0),
                    }
                ]
    except Exception as e:
        logger.debug("%s not available at %s: %s", name, base_url, e)
    return []


def get_musicgen_models(base_url: str = MUSICGEN_DEFAULT_URL) -> list[dict]:
    return _probe_service(base_url, "musicgen", fmt="audiocraft")


def get_bark_models(base_url: str = BARK_DEFAULT_URL) -> list[dict]:
    return _probe_service(base_url, "bark", fmt="bark")


def get_rvc_models(base_url: str = RVC_DEFAULT_URL) -> list[dict]:
    return _probe_service(base_url, "rvc", fmt="rvc")


def get_coqui_tts_models(base_url: str = COQUI_TTS_DEFAULT_URL) -> list[dict]:
    return _probe_service(base_url, "coqui-tts", fmt="xtts")


def get_stt_models(base_url: str = STT_DEFAULT_URL) -> list[dict]:
    """Probe stt-api /health and emit one entry per available whisper model.

    The stt-api lists its allowlist via the ``available_models`` field on
    ``/health`` (since v1.1). Older deployments without that field fall back
    to a single entry using ``default_model`` so we stay backward-compatible.

    Each emitted model_identifier is prefixed ``whisper-`` to keep it
    self-describing and to avoid colliding with same-named entries in other
    providers (e.g., an Ollama tag).
    """
    try:
        with httpx.Client(timeout=3.0) as client:
            resp = client.get(f"{base_url}/health")
            if resp.status_code != 200:
                return []
            data = resp.json()
    except Exception as e:
        logger.debug("stt not available at %s: %s", base_url, e)
        return []

    default_model = data.get("default_model")
    available = data.get("available_models") or ([default_model] if default_model else [])
    if not available:
        return []

    gpu_name = data.get("gpu_name") or data.get("gpu") or ""
    return [
        {
            "name": f"whisper-{m}",
            "model": m,
            "size": 0,
            "parameter_size": "",
            "quantization": "whisper",
            "family": "audio",
            "format": "whisper",
            "default": m == default_model,
            "gpu": gpu_name,
            "vram_used_mb": data.get("vram_used_mb", 0),
        }
        for m in available
    ]


def get_ltx_video_models(base_url: str = LTX_VIDEO_DEFAULT_URL) -> list[dict]:
    return _probe_service(base_url, "ltx-video", family="video", fmt="ltx-dit")


def get_wan_video_models(base_url: str = WAN_VIDEO_DEFAULT_URL) -> list[dict]:
    return _probe_service(base_url, "wan-video", family="video", fmt="wan-diffusers")


def get_comfyui_status(base_url: str = COMFYUI_DEFAULT_URL) -> dict | None:
    """Probe ComfyUI's /system_stats endpoint for liveness.

    ComfyUI is often run as a host-process (not in docker), so the
    docker-container scan can't auto-discover it. Probing the well-known
    port 8188 with ComfyUI's native /system_stats endpoint catches both
    deployment styles (host process AND container). Bob-api uses this
    signal to auto-register a ``comfyui`` provider for the agent's host.

    Returns the parsed status dict on a 200 OK (so bob-api can extract
    VRAM info if it ever wants to), or ``None`` if ComfyUI is not
    reachable at the configured URL.
    """
    try:
        with httpx.Client(timeout=3.0) as client:
            resp = client.get(f"{base_url}/system_stats")
            if resp.status_code == 200:
                data = resp.json()
                # Normalise: keep only the bits we know how to consume.
                # ComfyUI's payload has {"system": {...}, "devices": [{...}]}.
                system = data.get("system") or {}
                devices = data.get("devices") or []
                return {
                    "alive": True,
                    "base_url": base_url,
                    "os": system.get("os", ""),
                    "ram_total": system.get("ram_total", 0),
                    "ram_free": system.get("ram_free", 0),
                    "comfyui_version": system.get("comfyui_version", ""),
                    "device_count": len(devices),
                    "device_names": [d.get("name", "") for d in devices],
                }
    except Exception as e:
        logger.debug("comfyui not available at %s: %s", base_url, e)
    return None
