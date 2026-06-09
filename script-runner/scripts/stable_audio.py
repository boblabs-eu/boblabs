"""Stable Audio Open — Text-to-audio generation using Stability AI's open model.

BOB_SCRIPT_META:
{
  "name": "stable_audio",
  "description": "Generate audio (music or sound effects) from a text prompt using Stable Audio Open. Outputs a WAV file.",
  "env": "/home/bob5950x/stable_audio/.venv",
  "parameters": {
    "prompt": {"type": "string", "description": "Text description of the audio to generate", "required": true},
    "negative_prompt": {"type": "string", "description": "What to avoid in the generation", "required": false},
    "duration_sec": {"type": "number", "description": "Duration in seconds (default: 10, max: 47)", "required": false},
    "steps": {"type": "integer", "description": "Number of diffusion steps (default: 100)", "required": false},
    "cfg_scale": {"type": "number", "description": "Classifier-free guidance scale (default: 7.0)", "required": false},
    "seed": {"type": "integer", "description": "Random seed for reproducibility", "required": false}
  }
}

Requirements:
    pip install torch torchaudio diffusers transformers einops
"""

import os


def run(args: dict, output_dir: str) -> dict:
    prompt = args.get("prompt", "")
    if not prompt:
        return {"success": False, "message": "Missing required parameter: prompt"}

    negative_prompt = args.get("negative_prompt", "low quality, distorted")
    duration_sec = min(float(args.get("duration_sec", 10)), 47)
    steps = int(args.get("steps", 100))
    cfg_scale = float(args.get("cfg_scale", 7.0))
    seed = args.get("seed")

    try:
        import torch
        import torchaudio
        from diffusers import StableAudioPipeline
    except ImportError as e:
        return {
            "success": False,
            "message": f"Missing dependency: {e}. Install: pip install torch torchaudio diffusers transformers einops",
        }

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32

    model_id = os.environ.get("STABLE_AUDIO_MODEL", "stabilityai/stable-audio-open-1.0")

    try:
        pipe = StableAudioPipeline.from_pretrained(model_id, torch_dtype=dtype)
        pipe = pipe.to(device)
        if device == "cuda":
            pipe.enable_model_cpu_offload()
    except Exception as e:
        return {"success": False, "message": f"Failed to load model: {e}"}

    generator = torch.Generator(device=device)
    if seed is not None:
        generator.manual_seed(int(seed))

    try:
        audio = pipe(
            prompt=prompt,
            negative_prompt=negative_prompt,
            num_inference_steps=steps,
            audio_end_in_s=duration_sec,
            guidance_scale=cfg_scale,
            generator=generator,
        ).audios
    except Exception as e:
        return {"success": False, "message": f"Generation failed: {e}"}

    try:
        output = audio[0].T if len(audio[0].shape) > 1 else audio[0]
        if output.dim() == 1:
            output = output.unsqueeze(0)

        sample_rate = pipe.vae.sampling_rate if hasattr(pipe.vae, "sampling_rate") else 44100
        out_path = os.path.join(output_dir, "stable_audio_output.wav")
        torchaudio.save(out_path, output.cpu().float(), sample_rate)
    except Exception as e:
        return {"success": False, "message": f"Failed to save audio: {e}"}

    file_size = os.path.getsize(out_path)
    return {
        "success": True,
        "message": f"Generated {duration_sec}s audio ({file_size // 1024}KB) from: {prompt[:80]}",
        "files": ["stable_audio_output.wav"],
    }
