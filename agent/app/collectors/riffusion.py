"""Bob Manager Agent — Riffusion service discovery collector.

Probes a local riffusion-hobby API server and reports availability.
The riffusion-hobby API exposes /run_inference/ for music generation
but has no model listing endpoint, so we probe availability and report
a single "riffusion-v1" model.
"""

import logging

import httpx

logger = logging.getLogger(__name__)

RIFFUSION_DEFAULT_URL = "http://localhost:3013"


def get_riffusion_models(base_url: str = RIFFUSION_DEFAULT_URL) -> list[dict]:
    """Check if riffusion-hobby is running and return model info.

    Returns a single-element list if reachable, empty list otherwise.
    """
    try:
        with httpx.Client(timeout=3.0) as client:
            # GET /run_inference/ returns 405 (Method Not Allowed) — means server is alive
            resp = client.get(f"{base_url}/run_inference/")
            if resp.status_code in (200, 405, 422):
                return [
                    {
                        "name": "riffusion-v1",
                        "model": "riffusion-v1",
                        "size": 0,
                        "parameter_size": "",
                        "quantization": "fp32",
                        "family": "audio",
                        "format": "diffusion",
                    }
                ]
    except Exception as e:
        logger.debug("Riffusion not available at %s: %s", base_url, e)

    return []
