"""ComfyUI tool — queue workflows, manage inputs/outputs on a ComfyUI server."""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import time
import uuid as uuid_mod
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from app.services.tool_executor import ToolExecutor

logger = logging.getLogger(__name__)

# ── Provider resolution ──────────────────────────────────────────────────────


async def _resolve_provider(executor: ToolExecutor, server_name: str | None):
    """Return (provider, error_str). One of them is always None."""
    from sqlalchemy import select

    from app.models.orchestrator import AIProvider

    stmt = select(AIProvider).where(
        AIProvider.provider_type == "comfyui",
        AIProvider.is_active == True,
    )
    result = await executor.db.execute(stmt)
    providers = list(result.scalars().all())

    if not providers:
        return (
            None,
            "No active ComfyUI provider configured. Add one in Settings → AI Providers (type: comfyui).",
        )

    if server_name:
        # Exact name match first, then case-insensitive
        exact = [p for p in providers if p.name.lower() == server_name.lower()]
        if exact:
            return exact[0], None
        partial = [p for p in providers if server_name.lower() in p.name.lower()]
        if partial:
            return partial[0], None
        names = ", ".join(p.name for p in providers)
        return None, f"ComfyUI server '{server_name}' not found. Available: {names}"

    if len(providers) == 1:
        return providers[0], None

    names = ", ".join(p.name for p in providers)
    return None, f"Multiple ComfyUI servers configured. Specify server_name: {names}"


def _base_url(provider) -> str:
    return provider.base_url.rstrip("/")


# ── Tool schema ──────────────────────────────────────────────────────────────

TOOLS = {
    "comfyui": {
        "description": (
            "Interact with a ComfyUI server to run image/video/audio generation workflows. "
            "Actions: "
            "upload_input — upload a lab resource file to ComfyUI's input folder, returns comfyui_filename to use in workflow nodes (e.g. LoadImage); "
            "queue_workflow — submit a workflow JSON dict, wait for completion, download outputs to the lab output folder and return their paths + view URLs; "
            "get_status — get current queue depth and GPU VRAM usage; "
            "list_models — list available model files (optionally filtered by folder: checkpoints, loras, vae, controlnet, embeddings, etc.); "
            "interrupt — cancel the currently running generation; "
            "get_node_types — list all available ComfyUI node class names (for building workflows)."
        ),
        "parameters": {
            "action": {
                "type": "string",
                "description": "Action to perform: upload_input | queue_workflow | get_status | list_models | interrupt | get_node_types",
                "required": True,
            },
            "resource_filename": {
                "type": "string",
                "description": "[upload_input] Original filename of a lab resource to upload (e.g. 'my_photo.png').",
                "required": False,
            },
            "workflow_json": {
                "type": "object",
                "description": "[queue_workflow] The ComfyUI workflow as a JSON dict (API format, not UI format). Use comfyui_filename values from upload_input in LoadImage nodes.",
                "required": False,
            },
            "folder": {
                "type": "string",
                "description": "[list_models] Model folder to list (e.g. checkpoints, loras, vae, controlnet, embeddings). Omit to list all folder types.",
                "required": False,
            },
            "timeout": {
                "type": "integer",
                "description": "[queue_workflow] Max seconds to wait for the workflow to complete (default: 300).",
                "required": False,
            },
            "server_name": {
                "type": "string",
                "description": "Name of the ComfyUI provider to use. Required only when multiple ComfyUI servers are configured.",
                "required": False,
            },
        },
    },
}

# ── Handlers ─────────────────────────────────────────────────────────────────


async def comfyui(executor: ToolExecutor, args: dict) -> dict:
    action = (args.get("action") or "").strip()
    server_name = args.get("server_name") or None

    provider, err = await _resolve_provider(executor, server_name)
    if err:
        return {"success": False, "output": err}

    base = _base_url(provider)

    if action == "upload_input":
        return await _upload_input(executor, base, args)
    elif action == "queue_workflow":
        return await _queue_workflow(executor, base, args)
    elif action == "get_status":
        return await _get_status(base)
    elif action == "list_models":
        return await _list_models(base, args)
    elif action == "interrupt":
        return await _interrupt(base)
    elif action == "get_node_types":
        return await _get_node_types(base)
    else:
        return {
            "success": False,
            "output": f"Unknown action '{action}'. Valid: upload_input, queue_workflow, get_status, list_models, interrupt, get_node_types",
        }


# ── Action: upload_input ─────────────────────────────────────────────────────


async def _upload_input(executor: ToolExecutor, base: str, args: dict) -> dict:
    resource_filename = (args.get("resource_filename") or "").strip()
    if not resource_filename:
        return {"success": False, "output": "upload_input requires 'resource_filename'"}

    # Search workspace for the file (by original name or uuid-prefixed name)
    workspace = executor.workspace
    candidates = [
        workspace / resource_filename,
    ]
    # Also try looking up through symlink or uuid-prefixed version
    for f in workspace.iterdir():
        if f.is_file() and not f.is_symlink():
            if f.name.endswith("_" + resource_filename) or f.name == resource_filename:
                candidates.insert(0, f)

    file_path = None
    for c in candidates:
        resolved = c.resolve()
        if resolved.is_relative_to(workspace.resolve()) and resolved.is_file():
            file_path = resolved
            break
    # Symlinks resolve to their target — also accept symlinks in workspace
    if not file_path:
        for c in candidates:
            if c.is_file():
                file_path = c
                break

    if not file_path:
        return {
            "success": False,
            "output": f"File '{resource_filename}' not found in lab workspace.",
        }

    content_type, _ = mimetypes.guess_type(file_path.name)
    if not content_type:
        content_type = "application/octet-stream"

    file_bytes = file_path.read_bytes()

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            resp = await client.post(
                f"{base}/upload/image",
                files={"image": (file_path.name, file_bytes, content_type)},
                data={"type": "input", "overwrite": "true"},
            )
            if resp.status_code >= 400:
                return {
                    "success": False,
                    "output": f"ComfyUI upload failed ({resp.status_code}): {resp.text[:400]}",
                }
            data = resp.json()
    except Exception as e:
        return {"success": False, "output": f"ComfyUI upload request failed: {e}"}

    comfyui_filename = data.get("name", file_path.name)
    subfolder = data.get("subfolder", "")
    return {
        "success": True,
        "output": (
            f"File '{resource_filename}' uploaded to ComfyUI as '{comfyui_filename}'. "
            f"Use comfyui_filename='{comfyui_filename}' in your workflow's LoadImage (or similar) node."
        ),
        "comfyui_filename": comfyui_filename,
        "subfolder": subfolder,
        "type": data.get("type", "input"),
    }


# ── Action: queue_workflow ───────────────────────────────────────────────────


async def _queue_workflow(executor: ToolExecutor, base: str, args: dict) -> dict:
    workflow = args.get("workflow_json")
    if not workflow:
        return {
            "success": False,
            "output": "queue_workflow requires 'workflow_json' (ComfyUI API-format dict)",
        }

    if isinstance(workflow, str):
        try:
            workflow = json.loads(workflow)
        except json.JSONDecodeError as e:
            return {"success": False, "output": f"workflow_json is not valid JSON: {e}"}

    timeout = int(args.get("timeout") or 300)
    client_id = uuid_mod.uuid4().hex

    # Submit prompt
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            resp = await client.post(
                f"{base}/prompt",
                json={"prompt": workflow, "client_id": client_id},
            )
            if resp.status_code >= 400:
                return {
                    "success": False,
                    "output": f"ComfyUI queue error ({resp.status_code}): {resp.text[:500]}",
                }
            queued = resp.json()
    except Exception as e:
        return {"success": False, "output": f"Failed to queue workflow: {e}"}

    if "error" in queued:
        node_errors = queued.get("node_errors", {})
        error_detail = json.dumps(node_errors, indent=2) if node_errors else str(queued["error"])
        return {"success": False, "output": f"Workflow validation error:\n{error_detail}"}

    prompt_id = queued.get("prompt_id")
    if not prompt_id:
        return {"success": False, "output": f"ComfyUI did not return a prompt_id: {queued}"}

    # Poll /history/{prompt_id} until done or timeout
    deadline = time.monotonic() + timeout
    history_entry = None
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
        while time.monotonic() < deadline:
            await asyncio.sleep(2)
            try:
                resp = await client.get(f"{base}/history/{prompt_id}")
                if resp.status_code == 200:
                    data = resp.json()
                    if prompt_id in data:
                        history_entry = data[prompt_id]
                        break
            except Exception:
                pass  # Network hiccup — keep polling

    if not history_entry:
        return {
            "success": False,
            "output": f"Workflow timed out after {timeout}s (prompt_id={prompt_id}). "
            f"Use get_status to check the queue, or interrupt to cancel.",
        }

    # Check execution status
    status_info = history_entry.get("status", {})
    if status_info.get("status_str") == "error":
        messages = status_info.get("messages", [])
        err_msgs = [m for m in messages if m[0] == "execution_error"]
        if err_msgs:
            detail = err_msgs[0][1] if len(err_msgs[0]) > 1 else str(err_msgs)
            return {"success": False, "output": f"Workflow execution error: {detail}"}

    # Collect output images from all nodes
    outputs = history_entry.get("outputs", {})
    saved_files = []
    output_dir = executor.workspace / "output" / "comfyui"
    output_dir.mkdir(parents=True, exist_ok=True)

    from app.repositories.lab_repo import LabResourceRepository

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as dl_client:
        for _node_id, node_output in outputs.items():
            for key in ("images", "videos", "audio", "gifs"):
                for item in node_output.get(key, []):
                    fname = item.get("filename", "")
                    subfolder = item.get("subfolder", "")
                    ftype = item.get("type", "output")
                    if not fname:
                        continue

                    params = {"filename": fname, "type": ftype}
                    if subfolder:
                        params["subfolder"] = subfolder

                    view_url = f"{base}/view?" + "&".join(f"{k}={v}" for k, v in params.items())

                    try:
                        dl_resp = await dl_client.get(f"{base}/view", params=params)
                        if dl_resp.status_code >= 400:
                            logger.warning(
                                "ComfyUI view failed for %s: %s", fname, dl_resp.status_code
                            )
                            continue
                        file_bytes = dl_resp.content
                    except Exception as e:
                        logger.warning("ComfyUI download failed for %s: %s", fname, e)
                        continue

                    # Save to lab output directory
                    local_fname = f"comfyui_{uuid_mod.uuid4().hex[:6]}_{fname}"
                    local_path = output_dir / local_fname
                    local_path.write_bytes(file_bytes)
                    rel_path = f"output/comfyui/{local_fname}"
                    size_bytes = len(file_bytes)

                    # Detect content type
                    ct, _ = mimetypes.guess_type(fname)
                    ct = ct or "application/octet-stream"

                    # Classify resource type
                    ext = Path(fname).suffix.lower()
                    if ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}:
                        res_type = "image"
                    elif ext in {".mp4", ".webm", ".mov"}:
                        res_type = "file"
                    elif ext in {".mp3", ".wav", ".flac", ".ogg"}:
                        res_type = "file"
                    else:
                        res_type = "file"

                    # Insert LabResource DB row
                    repo = LabResourceRepository(executor.db)
                    await repo.create(
                        lab_id=executor.lab_id,
                        filename=f"output/comfyui/{local_fname}",
                        original_name=local_fname,
                        content_type=ct,
                        size_bytes=size_bytes,
                        resource_type=res_type,
                        description=f"ComfyUI output — prompt_id={prompt_id}",
                    )
                    await executor.db.commit()

                    saved_files.append(
                        {
                            "local_path": rel_path,
                            "comfyui_view_url": view_url,
                            "filename": local_fname,
                            "size_bytes": size_bytes,
                        }
                    )

    if not saved_files:
        return {
            "success": True,
            "output": f"Workflow completed (prompt_id={prompt_id}) but produced no downloadable output files.",
        }

    lines = [f"Workflow completed. {len(saved_files)} output file(s) saved:\n"]
    for f in saved_files:
        lines.append(f"  - {f['local_path']} ({f['size_bytes'] // 1024}KB)")
        lines.append(f"    View URL: {f['comfyui_view_url']}")

    return {
        "success": True,
        "output": "\n".join(lines),
        "files": saved_files,
        "prompt_id": prompt_id,
        "file_event": {
            "action": "created",
            "path": saved_files[0]["local_path"],
            "size_bytes": saved_files[0]["size_bytes"],
        }
        if saved_files
        else None,
    }


# ── Action: get_status ───────────────────────────────────────────────────────


async def _get_status(base: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            queue_resp, stats_resp = await asyncio.gather(
                client.get(f"{base}/queue"),
                client.get(f"{base}/system_stats"),
                return_exceptions=True,
            )

        result = {}

        if not isinstance(queue_resp, Exception) and queue_resp.status_code == 200:
            q = queue_resp.json()
            running = q.get("queue_running", [])
            pending = q.get("queue_pending", [])
            result["queue_running"] = len(running)
            result["queue_pending"] = len(pending)

        if not isinstance(stats_resp, Exception) and stats_resp.status_code == 200:
            s = stats_resp.json()
            system = s.get("system", {})
            devices = s.get("devices", [])
            result["comfyui_version"] = system.get("comfyui_version", "?")
            result["ram_free_gb"] = round(system.get("ram_free", 0) / 1e9, 2)
            result["ram_total_gb"] = round(system.get("ram_total", 0) / 1e9, 2)
            if devices:
                d = devices[0]
                result["gpu"] = d.get("name", "?")
                result["vram_free_gb"] = round(d.get("vram_free", 0) / 1e9, 2)
                result["vram_total_gb"] = round(d.get("vram_total", 0) / 1e9, 2)

        lines = [
            f"ComfyUI status (v{result.get('comfyui_version', '?')}):",
            f"  Queue: {result.get('queue_running', '?')} running, {result.get('queue_pending', '?')} pending",
            f"  RAM: {result.get('ram_free_gb', '?')} GB free / {result.get('ram_total_gb', '?')} GB total",
        ]
        if "gpu" in result:
            lines.append(
                f"  GPU: {result['gpu']} — VRAM {result.get('vram_free_gb', '?')} GB free / {result.get('vram_total_gb', '?')} GB total"
            )

        return {"success": True, "output": "\n".join(lines), **result}
    except Exception as e:
        return {"success": False, "output": f"Failed to get ComfyUI status: {e}"}


# ── Action: list_models ──────────────────────────────────────────────────────


async def _list_models(base: str, args: dict) -> dict:
    """List actually-available model files on the ComfyUI server.

    Filters out ComfyUI's empty-folder placeholder files (e.g. ``put_loras_here``)
    so callers only see real models that can be referenced in a workflow.
    """
    from app.services.comfyui_discovery import (
        _is_real_model_file,
        list_comfyui_folders,
    )

    folder = (args.get("folder") or "").strip()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            if folder:
                resp = await client.get(f"{base}/models/{folder}")
                if resp.status_code == 404:
                    folders = await list_comfyui_folders(base)
                    return {
                        "success": False,
                        "output": f"Folder '{folder}' not found. Available folders: {', '.join(folders)}",
                    }
                if resp.status_code >= 400:
                    return {
                        "success": False,
                        "output": f"ComfyUI error {resp.status_code}: {resp.text[:400]}",
                    }
                raw = resp.json() or []
                models = [m for m in raw if isinstance(m, str) and _is_real_model_file(m)]
                if not models:
                    return {
                        "success": True,
                        "output": f"No real models found in '{folder}' (server has only placeholder files).",
                        "models": [],
                    }
                model_list = "\n".join(f"  - {m}" for m in models)
                return {
                    "success": True,
                    "output": f"Models in '{folder}' ({len(models)}):\n{model_list}",
                    "models": models,
                }

            # No folder specified: enumerate every folder and return all real models,
            # so the agent can verify availability up front.
            folders = await list_comfyui_folders(base)
            all_models: dict[str, list[str]] = {}
            total = 0
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client2:
                for f in folders:
                    r = await client2.get(f"{base}/models/{f}")
                    if r.status_code >= 400:
                        continue
                    raw = r.json() or []
                    real = sorted(m for m in raw if isinstance(m, str) and _is_real_model_file(m))
                    if real:
                        all_models[f] = real
                        total += len(real)

            if total == 0:
                return {
                    "success": True,
                    "output": f"No real models installed on this ComfyUI server. Folders present: {', '.join(folders)}",
                    "folders": folders,
                    "models_by_folder": {},
                }

            lines = [
                f"Available models on ComfyUI ({total} total across {len(all_models)} folders):",
                "",
            ]
            for f in sorted(all_models):
                lines.append(f"[{f}] ({len(all_models[f])})")
                for m in all_models[f]:
                    lines.append(f"  - {m}")
                lines.append("")
            return {
                "success": True,
                "output": "\n".join(lines).rstrip(),
                "folders": folders,
                "models_by_folder": all_models,
                "total": total,
            }
    except Exception as e:
        return {"success": False, "output": f"Failed to list models: {e}"}


# ── Action: interrupt ────────────────────────────────────────────────────────


async def _interrupt(base: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            resp = await client.post(f"{base}/interrupt")
            if resp.status_code == 200:
                return {"success": True, "output": "ComfyUI: current generation interrupted."}
            return {"success": False, "output": f"Interrupt returned status {resp.status_code}"}
    except Exception as e:
        return {"success": False, "output": f"Failed to interrupt: {e}"}


# ── Action: get_node_types ───────────────────────────────────────────────────


async def _get_node_types(base: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            resp = await client.get(f"{base}/object_info")
            if resp.status_code >= 400:
                return {
                    "success": False,
                    "output": f"ComfyUI error {resp.status_code}: {resp.text[:400]}",
                }
            data = resp.json()

        node_names = sorted(data.keys())
        # Group by category for readability
        categories: dict[str, list[str]] = {}
        for name in node_names:
            cat = data[name].get("category", "other") if isinstance(data[name], dict) else "other"
            categories.setdefault(cat, []).append(name)

        lines = [f"ComfyUI node types ({len(node_names)} total):\n"]
        for cat in sorted(categories):
            lines.append(f"[{cat}]")
            lines.append("  " + ", ".join(categories[cat]))
            lines.append("")

        return {
            "success": True,
            "output": "\n".join(lines),
            "node_count": len(node_names),
            "node_names": node_names,
        }
    except Exception as e:
        return {"success": False, "output": f"Failed to get node types: {e}"}


# ── HANDLERS dict for auto-discovery ────────────────────────────────────────

HANDLERS = {
    "comfyui": comfyui,
}
