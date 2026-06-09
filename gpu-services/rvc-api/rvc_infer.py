"""RVC inference wrapper.

Provides a clean interface to the RVC pipeline for the API service.
Handles model loading, pitch extraction, and voice conversion.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np
import torch

logger = logging.getLogger("rvc-api.infer")

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
IS_HALF = DEVICE == "cuda"


def load_model(model_path: str, index_path: Optional[str] = None) -> dict:
    """Load an RVC model (.pth) and optional FAISS index (.index).

    Returns a dict with model components needed for inference.
    """
    from fairseq import checkpoint_utils

    logger.info("Loading model checkpoint from %s", model_path)
    cpt = torch.load(model_path, map_location="cpu", weights_only=False)
    tgt_sr = cpt.get("config", [0, 0, 0])[-1]  # Target sample rate from config
    if tgt_sr == 0:
        tgt_sr = 40000  # Default RVC sample rate

    # Determine model version and config
    if_f0 = cpt.get("f0", 1)
    version = cpt.get("version", "v1")

    # Build the synthesis model
    if version == "v1":
        from infer.lib.infer_pack.models import SynthesizerTrnMs256NSFsid as SynthModel

        net_g = SynthModel(*cpt["config"], is_half=IS_HALF)
    else:
        from infer.lib.infer_pack.models import SynthesizerTrnMs768NSFsid as SynthModel

        net_g = SynthModel(*cpt["config"], is_half=IS_HALF)

    # Load weights
    net_g.load_state_dict(cpt["weight"], strict=False)
    net_g.eval().to(DEVICE)
    if IS_HALF:
        net_g = net_g.half()

    # Load FAISS index if provided
    index = None
    if index_path and Path(index_path).exists():
        import faiss

        logger.info("Loading FAISS index from %s", index_path)
        index = faiss.read_index(index_path)
        if DEVICE == "cuda":
            # Keep index on CPU — GPU index uses too much VRAM for marginal gain
            pass

    # Load hubert model for feature extraction
    hubert_path = Path(__file__).parent / "hubert_base.pt"
    if not hubert_path.exists():
        # Try downloading from HuggingFace
        from huggingface_hub import hf_hub_download

        hubert_path = hf_hub_download(
            repo_id="lj1995/VoiceConversionWebUI", filename="hubert_base.pt"
        )

    models, _, _ = checkpoint_utils.load_model_ensemble_and_task([str(hubert_path)], suffix="")
    hubert_model = models[0].to(DEVICE)
    if IS_HALF:
        hubert_model = hubert_model.half()
    hubert_model.eval()

    return {
        "net_g": net_g,
        "hubert": hubert_model,
        "index": index,
        "tgt_sr": tgt_sr,
        "if_f0": if_f0,
        "version": version,
        "cpt": cpt,
    }


def infer(
    model_data: dict,
    audio: np.ndarray,
    sr: int,
    f0_up_key: int = 0,
    f0_method: str = "rmvpe",
    index_ratio: float = 0.75,
    filter_radius: int = 3,
    rms_mix_rate: float = 0.25,
    protect: float = 0.33,
) -> np.ndarray:
    """Run voice conversion on input audio.

    Args:
        model_data: Dict from load_model()
        audio: Input audio as numpy array (float32, mono)
        sr: Input sample rate
        f0_up_key: Pitch shift in semitones
        f0_method: Pitch extraction method
        index_ratio: Feature retrieval ratio
        filter_radius: Median filter for pitch smoothing
        rms_mix_rate: Volume envelope mixing
        protect: Voiceless consonant protection

    Returns:
        Output audio as numpy float32 array at target sample rate
    """
    import librosa
    from infer.modules.vc.pipeline import Pipeline

    net_g = model_data["net_g"]
    hubert = model_data["hubert"]
    index = model_data["index"]
    tgt_sr = model_data["tgt_sr"]
    if_f0 = model_data["if_f0"]
    version = model_data["version"]

    # Resample to 16kHz for feature extraction
    if sr != 16000:
        audio = librosa.resample(audio, orig_sr=sr, target_sr=16000)

    # Ensure mono float32
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    audio = audio.astype(np.float32)

    # Create pipeline and run
    pipeline = Pipeline(tgt_sr, DEVICE, IS_HALF)

    audio_out = pipeline.pipeline(
        hubert,
        net_g,
        0,  # sid
        audio,
        [0, 0, 0],  # times (unused tracking)
        f0_up_key,
        f0_method,
        index,
        index_ratio,
        if_f0,
        filter_radius,
        tgt_sr,
        0,  # resample_sr (0 = no resample)
        rms_mix_rate,
        version,
        protect,
    )

    return audio_out.astype(np.float32)
