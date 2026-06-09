"""Media generation tools: image_generate, audio_generate, media_pipeline, audio_mix, video_generate."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from app.services.tool_executor import ToolExecutor

logger = logging.getLogger(__name__)

# ── GPU slot management (module-level, shared across all executors) ──────
#
# P09 — semaphores are keyed by ``(host, port)`` so two GPU services on
# the same machine but different ports (e.g. riffusion :3013 +
# musicgen :3014) get independent queues. Previously the key was the
# bare hostname, which meant a long-running musicgen call would block
# all riffusion calls and vice versa even though they don't share the
# same backing model / VRAM allocation.
_gpu_slots: dict[tuple[str, int], asyncio.Semaphore] = {}
_gpu_slots_lock = asyncio.Lock()


def _slot_key_from_url(url: str) -> tuple[str, int]:
    """Extract the (host, port) tuple used to key the per-service GPU
    semaphore. Falls back to the raw URL string + sentinel port 0 when
    parsing fails so we never blow up on a malformed provider base_url.
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.hostname or url
    # Default to scheme-default port when not specified so two providers
    # on http://h and http://h:80 share a single semaphore (they're the
    # same actual endpoint).
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return (host, port)


async def _acquire_gpu_slot(host_or_url: str | tuple[str, int]) -> asyncio.Semaphore:
    """Get (or create) per-(host, port) GPU semaphore and acquire it.

    Accepts either the raw base_url string (convenience for callers that
    don't pre-parse) or an already-extracted ``(host, port)`` tuple.
    """
    key = host_or_url if isinstance(host_or_url, tuple) else _slot_key_from_url(host_or_url)
    if key not in _gpu_slots:
        async with _gpu_slots_lock:
            if key not in _gpu_slots:
                _gpu_slots[key] = asyncio.Semaphore(1)
    sem = _gpu_slots[key]
    await sem.acquire()
    return sem


# Back-compat alias — some callers (and any external tooling) still pass
# the URL directly; preserve the old name as a thin shim.
def _host_from_url(url: str) -> tuple[str, int]:
    return _slot_key_from_url(url)


TOOLS = {
    "image_generate": {
        "description": "Generate an image from a text prompt using a configured image generation API (Stable Diffusion, FLUX, etc). Returns the path to the generated image file.",
        "parameters": {
            "prompt": {
                "type": "string",
                "description": "Text description of the image to generate",
                "required": True,
            },
            "width": {
                "type": "integer",
                "description": "Image width in pixels (default: 1024)",
                "required": False,
            },
            "height": {
                "type": "integer",
                "description": "Image height in pixels (default: 1024)",
                "required": False,
            },
        },
    },
    "audio_generate": {
        "description": "Generate audio using a script runner on a connected agent. Supports various audio generation backends (riffusion, stable_audio, musicgen, bark, etc.)",
        "parameters": {
            "script": {
                "type": "string",
                "description": "Name of the audio generation script to use (e.g. riffusion, stable_audio, musicgen)",
                "required": True,
            },
            "prompt": {
                "type": "string",
                "description": "Text prompt describing the audio to generate",
                "required": True,
            },
            "duration_sec": {
                "type": "number",
                "description": "Duration in seconds (default depends on script)",
                "required": False,
            },
            "extra_args": {
                "type": "object",
                "description": "Additional script-specific arguments",
                "required": False,
            },
        },
    },
    "media_pipeline": {
        "description": "Run a media generation/processing pipeline (image, audio, video, or speech-to-text). Dispatches to registered pipeline backends like riffusion, bark, musicgen, coqui-tts, rvc, stt, sdxl, sd3, flux1, ltx-video, wan-video. The system automatically selects the least-loaded GPU server. Use 'params' for pipeline-specific options.",
        "parameters": {
            "pipeline": {
                "type": "string",
                "description": "Pipeline name (e.g. riffusion, bark, musicgen, coqui-tts, rvc, stt, sdxl, sd3, flux1, ltx-video, wan-video)",
                "required": True,
            },
            "prompt": {
                "type": "string",
                "description": "Text prompt for generation",
                "required": True,
            },
            "params": {
                "type": "object",
                "description": "Pipeline-specific parameters (see pipeline docs)",
                "required": False,
            },
        },
    },
    "audio_mix": {
        "description": "Mix, concatenate, or process audio files using FFmpeg. Supports operations: mix (overlay multiple tracks with optional volume weights), concat (join files sequentially), volume (adjust loudness), fade (in/out), normalize (loudness normalization via loudnorm), convert (format conversion), trim (cut segment), eq (parametric EQ). All file paths are relative to the lab workspace.",
        "parameters": {
            "operation": {
                "type": "string",
                "description": "Operation: mix, concat, volume, fade, normalize, convert, trim, eq",
                "required": True,
            },
            "input_files": {
                "type": "array",
                "description": "List of input file paths (relative to workspace)",
                "required": True,
            },
            "output_file": {
                "type": "string",
                "description": "Output file path (relative to workspace)",
                "required": True,
            },
            "params": {
                "type": "object",
                "description": "Operation-specific parameters. mix: {volumes: [0.8, 1.0]}. fade: {fade_in: 2, fade_out: 3}. volume: {volume: 1.5}. normalize: {target_lufs: -14}. convert: {format: 'mp3'}. trim: {start: '00:00:10', end: '00:01:00'}. eq: {eq_freq: 1000, eq_gain: 3, eq_width: 1.0}",
                "required": False,
            },
        },
    },
    "video_generate": {
        "description": "Generate a video by writing a React/Remotion component. Send the TSX source code and it will be rendered to MP4 via the Remotion API.",
        "parameters": {
            "code": {
                "type": "string",
                "description": "React/TSX component source code for the video. Must export a default component.",
                "required": True,
            },
            "width": {
                "type": "integer",
                "description": "Video width (default: 1920)",
                "required": False,
            },
            "height": {
                "type": "integer",
                "description": "Video height (default: 1080)",
                "required": False,
            },
            "fps": {
                "type": "integer",
                "description": "Frames per second (default: 30)",
                "required": False,
            },
            "duration_in_frames": {
                "type": "integer",
                "description": "Total frames (default: 120 = 4s at 30fps)",
                "required": False,
            },
            "props": {
                "type": "object",
                "description": "Props to pass to the React component",
                "required": False,
            },
        },
    },
}


async def image_generate(executor: ToolExecutor, args: dict) -> dict:
    prompt = args.get("prompt", "")
    if not prompt:
        return {"success": False, "output": "image_generate requires 'prompt'"}

    api_url = os.environ.get("IMAGE_GEN_API_URL", "").rstrip("/")
    if not api_url:
        return {
            "success": False,
            "output": "Image generation not configured. Set IMAGE_GEN_API_URL environment variable.",
        }

    width = int(args.get("width", 1024))
    height = int(args.get("height", 1024))
    api_key = os.environ.get("IMAGE_GEN_API_KEY", "")

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "prompt": prompt,
        "n": 1,
        "size": f"{width}x{height}",
        "response_format": "b64_json",
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            resp = await client.post(
                f"{api_url}/v1/images/generations",
                json=payload,
                headers=headers,
            )
            if resp.status_code >= 400:
                return {
                    "success": False,
                    "output": f"Image API error {resp.status_code}: {resp.text[:500]}",
                }
            data = resp.json()
    except Exception as e:
        return {"success": False, "output": f"Image generation request failed: {e}"}

    images = data.get("data", [])
    if not images:
        return {"success": False, "output": "Image API returned no images."}

    b64_data = images[0].get("b64_json", "")
    if not b64_data:
        return {"success": False, "output": "Image API returned no image data."}

    output_dir = executor.workspace / "output" / "generated_images"
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"gen_{int(time.time())}.png"
    target = output_dir / filename
    target.write_bytes(base64.b64decode(b64_data))
    rel_path = f"output/generated_images/{filename}"
    size_bytes = target.stat().st_size

    return {
        "success": True,
        "output": f"Image generated and saved to {rel_path} ({size_bytes} bytes).\n![generated]({rel_path})",
        "file_event": {
            "action": "created",
            "path": rel_path,
            "size_bytes": size_bytes,
        },
    }


async def audio_generate(executor: ToolExecutor, args: dict) -> dict:
    script = args.get("script", "").strip()
    prompt = args.get("prompt", "").strip()
    if not script:
        return {
            "success": False,
            "output": "audio_generate requires 'script' (e.g. riffusion, stable_audio, musicgen)",
        }
    if not prompt:
        return {"success": False, "output": "audio_generate requires 'prompt'"}

    from app.websocket.hub import manager as ws_manager

    agent_name = ws_manager.find_agent_for_script(script)
    if not agent_name:
        available = ws_manager.get_all_available_scripts()
        if available:
            names = ", ".join(s["name"] for s in available)
            return {
                "success": False,
                "output": f"Script '{script}' not found. Available scripts: {names}",
            }
        return {
            "success": False,
            "output": "No script runners connected. Ensure an agent with a script runner is online.",
        }

    script_args = {"prompt": prompt}
    duration = args.get("duration_sec")
    if duration is not None:
        script_args["duration_sec"] = float(duration)
    extra = args.get("extra_args")
    if isinstance(extra, dict):
        script_args.update(extra)

    import uuid

    request_id = str(uuid.uuid4())
    future = ws_manager.create_pending(request_id)

    sent = await ws_manager.send_to_agent(
        agent_name,
        {
            "type": "script.execute",
            "id": request_id,
            "payload": {
                "script": script,
                "arguments": script_args,
                "timeout_sec": executor.timeout_sec,
            },
        },
    )
    if not sent:
        return {"success": False, "output": f"Agent '{agent_name}' is not connected."}

    try:
        data = await asyncio.wait_for(future, timeout=executor.timeout_sec + 30)
    except asyncio.TimeoutError:
        return {
            "success": False,
            "output": f"Script '{script}' timed out waiting for agent response.",
        }

    if not data.get("success"):
        return {
            "success": False,
            "output": f"Script '{script}' failed: {data.get('message', 'unknown error')}",
        }

    output_dir = executor.workspace / "output" / "generated_audio"
    output_dir.mkdir(parents=True, exist_ok=True)
    saved_files = []
    for file_info in data.get("output_files", []):
        fname = file_info.get("name", "")
        b64 = file_info.get("base64", "")
        if not fname or not b64:
            continue
        target = output_dir / fname
        target.write_bytes(base64.b64decode(b64))
        rel_path = f"output/generated_audio/{fname}"
        saved_files.append({"path": rel_path, "size_bytes": target.stat().st_size})

    if not saved_files:
        return {
            "success": True,
            "output": f"Script ran but produced no files. Message: {data.get('message', '')}",
        }

    file_list = ", ".join(f"{f['path']} ({f['size_bytes'] // 1024}KB)" for f in saved_files)
    primary = saved_files[0]
    duration_info = f" in {data.get('duration_sec', '?')}s" if data.get("duration_sec") else ""
    return {
        "success": True,
        "output": f"Audio generated{duration_info}: {file_list}\nMessage: {data.get('message', '')}",
        "file_event": {
            "action": "created",
            "path": primary["path"],
            "size_bytes": primary["size_bytes"],
        },
    }


async def media_pipeline(executor: ToolExecutor, args: dict) -> dict:
    """Generic media pipeline tool — dispatches to registered pipelines."""
    pipeline_name = args.get("pipeline", "").strip()
    prompt = args.get("prompt", "").strip()
    _raw_params = args.get("params") or {}
    if isinstance(_raw_params, str):
        try:
            extra = json.loads(_raw_params)
        except json.JSONDecodeError:
            return {
                "success": False,
                "output": "media_pipeline 'params' must be a valid JSON object.",
            }
    else:
        extra = dict(_raw_params)

    if not pipeline_name:
        return {"success": False, "output": "media_pipeline requires 'pipeline' (e.g. riffusion)"}
    if not prompt:
        return {"success": False, "output": "media_pipeline requires 'prompt'"}

    if executor._allowed_pipelines and pipeline_name not in executor._allowed_pipelines:
        return {
            "success": False,
            "output": f"Pipeline '{pipeline_name}' is not enabled. Available: {', '.join(executor._allowed_pipelines)}",
        }

    from app.services.pipelines import PIPELINE_REGISTRY, get_pipeline

    if pipeline_name not in PIPELINE_REGISTRY:
        available = ", ".join(PIPELINE_REGISTRY.keys())
        return {
            "success": False,
            "output": f"Unknown pipeline '{pipeline_name}'. Registered: {available}",
        }

    from sqlalchemy import select

    from app.models.orchestrator import AIProvider

    stmt = select(AIProvider).where(
        AIProvider.provider_type == pipeline_name,
        AIProvider.is_active == True,
    )
    result = await executor.db.execute(stmt)
    providers = result.scalars().all()
    if not providers:
        return {
            "success": False,
            "output": f"No active '{pipeline_name}' provider configured. Check Settings → AI Providers.",
        }

    def _queue_depth(prov):
        # P09 — key by (host, port) so two services on the same machine
        # different ports get independent semaphores.
        slot_key = _slot_key_from_url(prov.base_url)
        sem = _gpu_slots.get(slot_key)
        if sem is None:
            return 0
        return 0 if sem._value > 0 else 1

    providers.sort(key=_queue_depth)

    input_file = extra.get("input_file")
    if input_file:
        fpath = executor.workspace / input_file
        if not fpath.resolve().is_relative_to(executor.workspace.resolve()):
            return {"success": False, "output": f"input_file path escapes workspace: {input_file}"}
        if not fpath.is_file():
            return {"success": False, "output": f"Input file not found: {input_file}"}
        raw_bytes = fpath.read_bytes()
        extra["input_audio_b64"] = base64.b64encode(raw_bytes).decode()
        extra["_audio_bytes"] = raw_bytes
        extra["_filename"] = fpath.name

    last_error = ""
    gen_result = None
    used_provider = None
    for provider in providers:
        slot_key = _slot_key_from_url(provider.base_url)
        pipeline = get_pipeline(pipeline_name, provider.base_url)

        params = pipeline.build_tool_params(prompt, extra)
        try:
            clean_params = pipeline.validate_params(params)
        except ValueError as e:
            return {"success": False, "output": f"Invalid parameters: {e}"}

        # P09 — render the (host, port) tuple as 'host:port' in the log.
        logger.info(
            "media_pipeline/%s: queuing on %s (slot=%s:%d)",
            pipeline_name,
            provider.name,
            slot_key[0],
            slot_key[1],
        )
        sem = await _acquire_gpu_slot(slot_key)
        try:
            gen_result = await pipeline.generate(clean_params)
            if gen_result.success:
                used_provider = provider
                break
            last_error = gen_result.error or "unknown error"
            logger.warning(
                "media_pipeline/%s: provider %s failed: %s — trying next",
                pipeline_name,
                provider.name,
                last_error,
            )
        except Exception as e:
            last_error = str(e)
            logger.warning(
                "media_pipeline/%s: provider %s exception: %s — trying next",
                pipeline_name,
                provider.name,
                last_error,
            )
        finally:
            sem.release()

    if gen_result is None or not gen_result.success:
        return {"success": False, "output": f"Pipeline error (all providers failed): {last_error}"}

    # ── Text-output pipelines (e.g. STT) ─────────
    if gen_result.media_type == "text":
        transcript = gen_result.raw.get("text", "")
        segments = gen_result.raw.get("segments", [])
        language = gen_result.raw.get("language", "unknown")
        duration = gen_result.duration_s

        output_dir = executor.workspace / "output"
        output_dir.mkdir(exist_ok=True)
        ts = int(time.time())
        fname = f"transcript_{ts}.txt"
        fpath = output_dir / fname
        fpath.write_text(transcript, encoding="utf-8")
        rel_path = f"output/{fname}"

        provider_info = f" via {used_provider.name}" if used_provider else ""
        dur_info = f" ({duration:.1f}s audio)" if duration else ""
        seg_count = len(segments)

        display = transcript[:3000]
        if len(transcript) > 3000:
            display += "\n... [truncated, see full transcript file]"

        return {
            "success": True,
            "output": (
                f"Transcription complete{provider_info}{dur_info}: "
                f"{seg_count} segments, lang={language}\n"
                f"Saved to: {rel_path}\n\n{display}"
            ),
            "file_event": {
                "action": "created",
                "path": rel_path,
                "size_bytes": len(transcript.encode("utf-8")),
            },
        }

    # ── Media-output pipelines (audio/image/video) ─────────
    media_dir = f"generated_{gen_result.media_type or 'media'}"
    output_dir = executor.workspace / "output" / media_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    saved_files = []

    ext_map = {"audio": "wav", "image": "png", "video": "mp4"}

    if gen_result.media_url:
        media_b64 = (
            gen_result.media_url.split(",", 1)[-1]
            if "," in gen_result.media_url
            else gen_result.media_url
        )
        ext = ext_map.get(gen_result.media_type, "bin")
        if gen_result.media_url.startswith("data:audio/mpeg"):
            ext = "mp3"
        elif gen_result.media_url.startswith("data:audio/wav"):
            ext = "wav"
        fname = f"{pipeline_name}_{ts}.{ext}"
        fpath = output_dir / fname
        fpath.write_bytes(base64.b64decode(media_b64))
        saved_files.append(
            {
                "path": f"output/{media_dir}/{fname}",
                "size_bytes": fpath.stat().st_size,
                "type": gen_result.media_type,
            }
        )

    if gen_result.preview_url:
        preview_b64 = (
            gen_result.preview_url.split(",", 1)[-1]
            if "," in gen_result.preview_url
            else gen_result.preview_url
        )
        pfname = f"{pipeline_name}_{ts}_preview.jpg"
        pfpath = output_dir / pfname
        pfpath.write_bytes(base64.b64decode(preview_b64))
        saved_files.append(
            {
                "path": f"output/{media_dir}/{pfname}",
                "size_bytes": pfpath.stat().st_size,
                "type": "preview",
            }
        )

    for output_name, output_b64 in gen_result.extra_outputs.items():
        raw_b64 = output_b64.split(",", 1)[-1] if "," in output_b64 else output_b64
        ext = ext_map.get(gen_result.media_type, "bin")
        efname = f"{pipeline_name}_{ts}_{output_name}.{ext}"
        efpath = output_dir / efname
        efpath.write_bytes(base64.b64decode(raw_b64))
        saved_files.append(
            {
                "path": f"output/{media_dir}/{efname}",
                "size_bytes": efpath.stat().st_size,
                "type": output_name,
            }
        )

    if not saved_files:
        return {"success": True, "output": "Pipeline ran but produced no output files."}

    summary = pipeline.format_summary(clean_params)
    provider_info = f" via {used_provider.name}" if used_provider else ""
    dur = f" ({gen_result.duration_s:.1f}s)" if gen_result.duration_s else ""
    file_list = ", ".join(f"{f['path']} ({f['size_bytes'] // 1024}KB)" for f in saved_files)
    primary = next((f for f in saved_files if f["type"] != "preview"), saved_files[0])

    return {
        "success": True,
        "output": f"Media generated via {pipeline_name}{provider_info}{dur}: {file_list}\n{summary}",
        "file_event": {
            "action": "created",
            "path": primary["path"],
            "size_bytes": primary["size_bytes"],
        },
    }


async def audio_mix(executor: ToolExecutor, args: dict) -> dict:
    operation = (args.get("operation") or "").strip().lower()
    input_files = args.get("input_files") or []
    output_file = (args.get("output_file") or "").strip()
    params = args.get("params") or {}

    VALID_OPS = {"mix", "concat", "volume", "fade", "normalize", "convert", "trim", "eq"}
    if operation not in VALID_OPS:
        return {
            "success": False,
            "output": f"Invalid operation '{operation}'. Must be one of: {', '.join(sorted(VALID_OPS))}",
        }
    if not output_file:
        return {"success": False, "output": "output_file is required"}
    if not input_files:
        return {"success": False, "output": "At least one input_files entry is required"}

    ws = executor.workspace.resolve()

    resolved_inputs: list[str] = []
    for rel in input_files:
        p = (executor.workspace / rel).resolve()
        if not p.is_relative_to(ws):
            return {"success": False, "output": f"Input path escapes workspace: {rel}"}
        if not p.is_file():
            return {"success": False, "output": f"Input file not found: {rel}"}
        resolved_inputs.append(str(p))

    out_path = (executor.workspace / output_file).resolve()
    if not out_path.is_relative_to(ws):
        return {"success": False, "output": f"Output path escapes workspace: {output_file}"}
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cmd: list[str] = ["ffmpeg", "-y"]

    if operation == "mix":
        for f in resolved_inputs:
            cmd += ["-i", f]
        n = len(resolved_inputs)
        volumes = params.get("volumes")
        if volumes and len(volumes) == n:
            filter_parts = []
            for i, v in enumerate(volumes):
                filter_parts.append(f"[{i}:a]volume={float(v)}[a{i}]")
            mix_inputs = "".join(f"[a{i}]" for i in range(n))
            filter_parts.append(f"{mix_inputs}amix=inputs={n}:duration=longest[out]")
            cmd += ["-filter_complex", ";".join(filter_parts), "-map", "[out]"]
        else:
            cmd += ["-filter_complex", f"amix=inputs={n}:duration=longest"]
        cmd.append(str(out_path))

    elif operation == "concat":
        for f in resolved_inputs:
            cmd += ["-i", f]
        n = len(resolved_inputs)
        concat_inputs = "".join(f"[{i}:a]" for i in range(n))
        cmd += ["-filter_complex", f"{concat_inputs}concat=n={n}:v=0:a=1[out]", "-map", "[out]"]
        cmd.append(str(out_path))

    elif operation == "volume":
        vol = float(params.get("volume", 1.0))
        cmd += ["-i", resolved_inputs[0], "-af", f"volume={vol}", str(out_path)]

    elif operation == "fade":
        fade_in = float(params.get("fade_in", 0))
        fade_out = float(params.get("fade_out", 0))
        filters = []
        if fade_in > 0:
            filters.append(f"afade=t=in:st=0:d={fade_in}")
        if fade_out > 0:
            filters.append(f"afade=t=out:st=-1:d={fade_out}")
        if not filters:
            return {
                "success": False,
                "output": "fade requires at least one of fade_in or fade_out > 0",
            }
        af = ",".join(filters)
        cmd += ["-i", resolved_inputs[0], "-af", af, str(out_path)]

    elif operation == "normalize":
        target_lufs = float(params.get("target_lufs", -14))
        cmd += [
            "-i",
            resolved_inputs[0],
            "-af",
            f"loudnorm=I={target_lufs}:dual_mono=true:print_format=summary",
            str(out_path),
        ]

    elif operation == "convert":
        fmt = params.get("format", "wav")
        allowed_formats = {"wav", "mp3", "flac", "ogg", "aac", "m4a"}
        if fmt not in allowed_formats:
            return {
                "success": False,
                "output": f"Unsupported format '{fmt}'. Allowed: {', '.join(sorted(allowed_formats))}",
            }
        cmd += ["-i", resolved_inputs[0], str(out_path)]

    elif operation == "trim":
        start = params.get("start")
        end = params.get("end")
        if start is not None:
            cmd += ["-ss", str(start)]
        cmd += ["-i", resolved_inputs[0]]
        if end is not None:
            cmd += ["-to", str(end)]
        cmd += ["-c", "copy", str(out_path)]

    elif operation == "eq":
        freq = float(params.get("eq_freq", 1000))
        gain = float(params.get("eq_gain", 0))
        width = float(params.get("eq_width", 1.0))
        cmd += [
            "-i",
            resolved_inputs[0],
            "-af",
            f"equalizer=f={freq}:width_type=o:width={width}:g={gain}",
            str(out_path),
        ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    except asyncio.TimeoutError:
        return {"success": False, "output": "FFmpeg timed out after 120s"}
    except FileNotFoundError:
        return {"success": False, "output": "ffmpeg not found. Is it installed in the container?"}

    if proc.returncode != 0:
        err = stderr.decode(errors="replace")[-500:]
        return {"success": False, "output": f"FFmpeg failed (rc={proc.returncode}): {err}"}

    if not out_path.is_file():
        return {"success": False, "output": "FFmpeg completed but output file was not created"}

    size = out_path.stat().st_size
    rel_out = str(out_path.relative_to(executor.workspace))
    return {
        "success": True,
        "output": f"audio_mix:{operation} complete → {rel_out} ({size // 1024}KB)",
        "file_event": {"action": "created", "path": rel_out, "size_bytes": size},
    }


async def video_generate(executor: ToolExecutor, args: dict) -> dict:
    code = args.get("code", "").strip()
    if not code:
        return {
            "success": False,
            "output": "video_generate requires 'code' (React/TSX component source)",
        }

    remotion_url = os.environ.get("REMOTION_API_URL", "http://bob-remotion:3020").rstrip("/")

    width = int(args.get("width", 1920))
    height = int(args.get("height", 1080))
    fps = int(args.get("fps", 30))
    duration_in_frames = int(args.get("duration_in_frames", 120))
    props = args.get("props") or {}

    payload = {
        "code": code,
        "composition_id": "Main",
        "width": width,
        "height": height,
        "fps": fps,
        "duration_in_frames": duration_in_frames,
        "codec": "h264",
        "props": props,
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(600.0)) as client:
            resp = await client.post(f"{remotion_url}/render", json=payload)
            if resp.status_code >= 400:
                body = (
                    resp.json()
                    if resp.headers.get("content-type", "").startswith("application/json")
                    else {"error": resp.text[:1000]}
                )
                return {
                    "success": False,
                    "output": f"Remotion render error: {body.get('error', resp.text[:500])}",
                }
            data = resp.json()
    except httpx.TimeoutException:
        return {
            "success": False,
            "output": "Remotion render timed out (600s limit). Try reducing duration_in_frames or resolution.",
        }
    except Exception as e:
        return {"success": False, "output": f"Remotion API request failed: {e}"}

    if not data.get("success"):
        return {
            "success": False,
            "output": f"Remotion render failed: {data.get('error', 'unknown error')}",
        }

    b64_data = data.get("video_base64", "")
    if not b64_data:
        return {"success": False, "output": "Remotion API returned no video data."}

    output_dir = executor.workspace / "output" / "generated_videos"
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"remotion_{int(time.time())}.mp4"
    target = output_dir / filename
    target.write_bytes(base64.b64decode(b64_data))
    rel_path = f"output/generated_videos/{filename}"
    size_bytes = target.stat().st_size

    duration_s = data.get("duration_seconds", duration_in_frames / fps)
    info = f"{data.get('width', width)}x{data.get('height', height)} @ {data.get('fps', fps)}fps, {duration_s:.1f}s"

    return {
        "success": True,
        "output": f"Video generated and saved to {rel_path} ({size_bytes} bytes, {info}).",
        "file_event": {
            "action": "created",
            "path": rel_path,
            "size_bytes": size_bytes,
        },
    }


HANDLERS = {
    "image_generate": image_generate,
    "audio_generate": audio_generate,
    "media_pipeline": media_pipeline,
    "audio_mix": audio_mix,
    "video_generate": video_generate,
}
