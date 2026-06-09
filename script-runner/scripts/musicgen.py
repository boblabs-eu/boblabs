"""MusicGen — Text-to-music generation using Meta's MusicGen model.

BOB_SCRIPT_META:
{
  "name": "musicgen",
  "description": "Generate music from a text prompt using Meta's MusicGen model. Supports small/medium/large variants. Outputs a WAV file.",
  "parameters": {
    "prompt": {"type": "string", "description": "Text description of the music to generate", "required": true},
    "duration_sec": {"type": "number", "description": "Duration in seconds (default: 10, max: 30)", "required": false},
    "model_size": {"type": "string", "description": "Model variant: small, medium, or large (default: medium)", "required": false},
    "temperature": {"type": "number", "description": "Sampling temperature (default: 1.0)", "required": false},
    "top_k": {"type": "integer", "description": "Top-K sampling (default: 250)", "required": false}
  }
}

Requirements:
    pip install torch torchaudio transformers audiocraft scipy
"""

import os


def run(args: dict, output_dir: str) -> dict:
    prompt = args.get("prompt", "")
    if not prompt:
        return {"success": False, "message": "Missing required parameter: prompt"}

    duration_sec = min(float(args.get("duration_sec", 10)), 30)
    model_size = args.get("model_size", "medium")
    temperature = float(args.get("temperature", 1.0))
    top_k = int(args.get("top_k", 250))

    if model_size not in ("small", "medium", "large"):
        model_size = "medium"

    try:
        import torch  # noqa: F401 — availability probe
        import torchaudio  # noqa: F401 — availability probe
        from audiocraft.models import MusicGen
    except ImportError as e:
        return {
            "success": False,
            "message": f"Missing dependency: {e}. Install: pip install torch torchaudio audiocraft",
        }

    model_id = os.environ.get("MUSICGEN_MODEL", f"facebook/musicgen-{model_size}")

    try:
        model = MusicGen.get_pretrained(model_id)
        model.set_generation_params(
            duration=duration_sec,
            temperature=temperature,
            top_k=top_k,
        )
    except Exception as e:
        return {"success": False, "message": f"Failed to load model: {e}"}

    try:
        wav = model.generate([prompt])
    except Exception as e:
        return {"success": False, "message": f"Generation failed: {e}"}

    try:
        audio = wav[0].cpu()
        sample_rate = model.sample_rate
        out_path = os.path.join(output_dir, "musicgen_output.wav")
        torchaudio.save(out_path, audio, sample_rate)
    except Exception as e:
        return {"success": False, "message": f"Failed to save audio: {e}"}

    file_size = os.path.getsize(out_path)
    return {
        "success": True,
        "message": f"Generated {duration_sec}s music ({file_size // 1024}KB) using {model_id}: {prompt[:80]}",
        "files": ["musicgen_output.wav"],
    }
