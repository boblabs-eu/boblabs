"""Riffusion — Text-to-music generation via the Riffusion pipeline.

BOB_SCRIPT_META:
{
  "name": "riffusion",
  "description": "Generate music from a text prompt using Riffusion (spectrogram diffusion). Outputs a WAV file.",
  "env": "conda:riffusion-old",
  "parameters": {
    "prompt": {"type": "string", "description": "Text description of the music to generate", "required": true},
    "negative_prompt": {"type": "string", "description": "What to avoid in the generation", "required": false},
    "duration_sec": {"type": "number", "description": "Duration in seconds (default: 10, max: 30)", "required": false},
    "seed": {"type": "integer", "description": "Random seed for reproducibility", "required": false}
  }
}

Requirements (install in the script-runner venv or system):
    pip install riffusion torch torchaudio diffusers transformers scipy
"""

import os


def run(args: dict, output_dir: str) -> dict:
    prompt = args.get("prompt", "")
    if not prompt:
        return {"success": False, "message": "Missing required parameter: prompt"}

    negative_prompt = args.get("negative_prompt", "")
    duration_sec = min(float(args.get("duration_sec", 10)), 30)
    seed = args.get("seed")

    try:
        import numpy as np
        import scipy.io.wavfile as wavfile
        import torch
        from diffusers import StableDiffusionPipeline
    except ImportError as e:
        return {
            "success": False,
            "message": f"Missing dependency: {e}. Install: pip install torch diffusers scipy numpy",
        }

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32

    # Load riffusion model
    model_id = os.environ.get("RIFFUSION_MODEL", "riffusion/riffusion-model-v1")
    try:
        pipe = StableDiffusionPipeline.from_pretrained(model_id, torch_dtype=dtype)
        pipe = pipe.to(device)
        if device == "cuda":
            pipe.enable_attention_slicing()
    except Exception as e:
        return {"success": False, "message": f"Failed to load model: {e}"}

    generator = torch.Generator(device=device)
    if seed is not None:
        generator.manual_seed(int(seed))

    # Generate spectrogram image
    try:
        result = pipe(
            prompt=prompt,
            negative_prompt=negative_prompt or None,
            width=512,
            height=512,
            num_inference_steps=50,
            generator=generator,
        )
        spec_image = result.images[0]
    except Exception as e:
        return {"success": False, "message": f"Generation failed: {e}"}

    # Convert spectrogram to audio
    try:
        spec_arr = np.array(spec_image.convert("L"), dtype=np.float32) / 255.0
        # Simple spectrogram-to-audio via Griffin-Lim approximation
        n_fft = 1024
        hop_length = 256
        sample_rate = 44100
        n_samples = int(duration_sec * sample_rate)

        # Resize spectrogram to match desired frequency bins
        from PIL import Image

        spec_resized = (
            np.array(
                Image.fromarray((spec_arr * 255).astype(np.uint8)).resize(
                    (n_samples // hop_length, n_fft // 2 + 1)
                ),
                dtype=np.float32,
            )
            / 255.0
        )

        # Reconstruct magnitude spectrogram and apply Griffin-Lim
        magnitude = spec_resized.T * 100  # scale up
        phase = np.random.uniform(0, 2 * np.pi, magnitude.shape)
        for _ in range(32):  # Griffin-Lim iterations
            stft = magnitude * np.exp(1j * phase)
            audio = np.fft.irfft(stft, axis=0).flatten()[:n_samples]
            recon = np.fft.rfft(
                np.lib.stride_tricks.sliding_window_view(np.pad(audio, (0, n_fft - 1)), n_fft)[
                    ::hop_length
                ],
                axis=1,
            ).T
            phase = np.angle(recon)

        # Normalize
        audio = audio / (np.max(np.abs(audio)) + 1e-8)
        audio_int16 = (audio * 32767).astype(np.int16)

        out_path = os.path.join(output_dir, "riffusion_output.wav")
        wavfile.write(out_path, sample_rate, audio_int16)
    except Exception as e:
        # Fallback: just save the spectrogram image
        spec_path = os.path.join(output_dir, "riffusion_spectrogram.png")
        spec_image.save(spec_path)
        return {
            "success": True,
            "message": f"Generated spectrogram (audio conversion failed: {e}). Spectrogram saved.",
            "files": ["riffusion_spectrogram.png"],
        }

    return {
        "success": True,
        "message": f"Generated {duration_sec}s audio track from prompt: {prompt[:80]}",
        "files": ["riffusion_output.wav"],
    }
