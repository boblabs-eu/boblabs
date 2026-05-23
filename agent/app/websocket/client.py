"""Bob Manager Agent — WebSocket client.

Connects to the control plane and handles bidirectional communication.
"""

import asyncio
import json
import logging
import socket
from datetime import datetime, timezone

import websockets

from app.config import config
from app.collectors.cpu import get_cpu_usage, get_cpu_temperature
from app.collectors.gpu import get_gpu_info, get_gpu_metrics
from app.collectors.memory import get_memory_usage
from app.collectors.network import get_network_io
from app.collectors.disk import get_disk_usage
from app.collectors.system import get_os_info, get_software_versions
from app.collectors.docker import get_docker_containers, get_docker_stats
from app.collectors.ollama import get_ollama_models
from app.collectors.riffusion import get_riffusion_models
from app.collectors.gpu_services import get_musicgen_models, get_bark_models, get_rvc_models, get_coqui_tts_models, get_stt_models, get_ltx_video_models, get_wan_video_models, get_comfyui_status
from app.collectors.script_runner import get_script_runner_scripts
from app.inspectors.processes import get_top_processes
from app.inspectors.services import get_services_grouped
from app.version import __version__ as agent_version
from app.inspectors.crontab import get_crontabs
from app.inspectors.ports import get_listening_ports
from app.inspectors.firewall import get_firewall_status
from app.executor.runner import run_command
from app.executor.terminal import terminal_manager

logger = logging.getLogger(__name__)


class AgentWebSocketClient:
    """WebSocket client that connects to a single control plane."""

    def __init__(self, control_plane_url: str) -> None:
        self.control_plane_url = control_plane_url
        self.ws = None
        self._running = True

    async def connect(self) -> None:
        """Connect to control plane with auto-reconnect."""
        while self._running:
            try:
                logger.info("Connecting to %s ...", self.control_plane_url)
                async with websockets.connect(
                    self.control_plane_url,
                    open_timeout=30,
                    ping_interval=20,
                    ping_timeout=20,
                    max_size=10 * 1024 * 1024,  # 10MB
                ) as ws:
                    self.ws = ws
                    await self._register()
                    await asyncio.gather(
                        self._message_loop(),
                        self._heartbeat_loop(),
                        self._metrics_loop(),
                    )
            except (
                websockets.ConnectionClosed,
                ConnectionRefusedError,
                OSError,
            ) as e:
                logger.warning(
                    "Connection lost (%s): %s. Reconnecting in 5s...",
                    type(e).__name__, e or "(no details)",
                )
                terminal_manager.close_all()
                self.ws = None
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(
                    "Unexpected error (%s): %s. Reconnecting in 10s...",
                    type(e).__name__, e,
                )
                terminal_manager.close_all()
                self.ws = None
                await asyncio.sleep(10)

    async def _register(self) -> None:
        """Send registration message to control plane."""
        os_info = get_os_info()
        gpu_info = get_gpu_info()
        sw_versions = get_software_versions()
        scripts = get_script_runner_scripts(config.script_runner_url)
        _runner_port = _get_script_runner_port()

        registration = {
            "type": "agent.register",
            "payload": {
                "name": config.agent_name,
                "token": config.agent_secret,
                "host": _get_local_ip(),
                "port": config.metrics_port,
                "os_info": {**os_info, **sw_versions},
                "gpu_info": {"gpus": gpu_info},
                "agent_version": agent_version,
                "script_runner": {
                    "port": _runner_port,
                    "scripts": scripts,
                } if scripts else None,
            },
        }

        await self.ws.send(json.dumps(registration))
        response = json.loads(await self.ws.recv())

        if response.get("type") == "register.ack":
            logger.info("Registered with control plane as '%s'", config.agent_name)
        else:
            logger.error("Registration failed: %s", response)
            raise ConnectionError("Registration rejected")

    async def _message_loop(self) -> None:
        """Listen for messages from the control plane."""
        async for raw in self.ws:
            try:
                data = json.loads(raw)
                await self._handle_message(data)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON received")
            except Exception as e:
                logger.error("Error handling message: %s", e)

    async def _handle_message(self, data: dict) -> None:
        """Dispatch incoming control plane messages."""
        msg_type = data.get("type", "")
        msg_id = data.get("id", "")
        payload = data.get("payload", {})

        if msg_type in ("command.execute", "workflow.step.execute"):
            # Execute command with streaming
            command = payload.get("command", "")
            logger.info("Executing command: %s", command[:100])

            async def on_stdout(line: str):
                await self.ws.send(json.dumps({
                    "type": "agent.command.output",
                    "id": msg_id,
                    "payload": {"stream": "stdout", "line": line},
                }))

            async def on_stderr(line: str):
                await self.ws.send(json.dumps({
                    "type": "agent.command.output",
                    "id": msg_id,
                    "payload": {"stream": "stderr", "line": line},
                }))

            result = await run_command(command, on_stdout=on_stdout, on_stderr=on_stderr)

            await self.ws.send(json.dumps({
                "type": "agent.command.complete",
                "id": msg_id,
                "payload": result,
            }))

        elif msg_type == "command.cancel":
            # TODO: implement command cancellation
            logger.info("Cancel requested for: %s", msg_id)

        elif msg_type == "terminal.open":
            cols = payload.get("cols", 120)
            rows = payload.get("rows", 40)
            session_id = payload.get("session_id", msg_id)
            logger.info("Opening terminal session %s (%dx%d)", session_id, cols, rows)
            terminal_manager.create_session(session_id, cols, rows)

            async def send_output(data: str, sid=session_id):
                await self.ws.send(json.dumps({
                    "type": "agent.terminal.output",
                    "id": sid,
                    "payload": {"data": data},
                }))

            await terminal_manager.start_output_loop(session_id, send_output)
            await self.ws.send(json.dumps({
                "type": "agent.terminal.opened",
                "id": session_id,
                "payload": {"status": "ok"},
            }))

        elif msg_type == "terminal.input":
            session_id = payload.get("session_id", msg_id)
            session = terminal_manager.get_session(session_id)
            if session:
                input_data = payload.get("data", "")
                logger.debug("Terminal input for %s: %r", session_id, input_data[:50])
                session.write(input_data)
            else:
                logger.warning("Terminal input for unknown session: %s", session_id)

        elif msg_type == "terminal.resize":
            session_id = payload.get("session_id", msg_id)
            session = terminal_manager.get_session(session_id)
            if session:
                session.resize(payload.get("cols", 120), payload.get("rows", 40))

        elif msg_type == "terminal.close":
            session_id = payload.get("session_id", msg_id)
            logger.info("Closing terminal session %s", session_id)
            terminal_manager.close_session(session_id)

        elif msg_type == "ai.models.discover":
            # Report available Ollama models to control plane
            models = get_ollama_models()
            await self.ws.send(json.dumps({
                "type": "agent.ai.models",
                "id": msg_id,
                "payload": {"models": models},
            }))

        elif msg_type == "inspection.request":
            kind = payload.get("kind", "")
            result = await self._handle_inspection(kind)
            await self.ws.send(json.dumps({
                "type": "agent.inspection.result",
                "id": msg_id,
                "payload": {"kind": kind, "data": result},
            }))

        elif msg_type == "script.execute":
            # Execute a script on the local script runner
            script_name = payload.get("script", "")
            arguments = payload.get("arguments", {})
            timeout_sec = payload.get("timeout_sec", 600)
            logger.info("Script execution requested: %s", script_name)
            result = await self._execute_script(script_name, arguments, timeout_sec)
            await self.ws.send(json.dumps({
                "type": "agent.script.result",
                "id": msg_id,
                "payload": result,
            }))

    async def _handle_inspection(self, kind: str) -> dict | list:
        """Handle system inspection requests."""
        if kind == "processes":
            return get_top_processes()
        elif kind == "services":
            return get_services_grouped()
        elif kind == "crontabs":
            return get_crontabs()
        elif kind == "ports":
            return get_listening_ports()
        elif kind == "firewall":
            return get_firewall_status()
        else:
            return {"error": f"Unknown inspection type: {kind}"}

    async def _execute_script(self, script_name: str, arguments: dict, timeout_sec: int = 600) -> dict:
        """Execute a script on the local script runner via HTTP."""
        import httpx as _httpx

        runner_url = config.script_runner_url.rstrip("/")
        try:
            async with _httpx.AsyncClient(timeout=_httpx.Timeout(float(timeout_sec) + 30)) as client:
                resp = await client.post(
                    f"{runner_url}/scripts/{script_name}/run",
                    json={"arguments": arguments, "timeout_sec": timeout_sec},
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.error("Script runner call failed for %s: %s", script_name, e)
            return {"success": False, "message": f"Script runner error: {e}"}

    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeats."""
        while self._running:
            await asyncio.sleep(config.heartbeat_interval)
            try:
                await self.ws.send(json.dumps({
                    "type": "agent.heartbeat",
                    "payload": {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                }))
            except Exception:
                break

    async def _metrics_loop(self) -> None:
        """Send periodic metrics to control plane."""
        while self._running:
            await asyncio.sleep(config.metrics_interval)
            try:
                metrics = _collect_all_metrics()
                await self.ws.send(json.dumps({
                    "type": "agent.metrics",
                    "payload": metrics,
                }))
            except Exception:
                break

    def stop(self) -> None:
        """Stop the client."""
        self._running = False


def _collect_all_metrics() -> dict:
    """Collect all metrics into a single payload."""
    mem = get_memory_usage()
    net = get_network_io()
    gpu_metrics = get_gpu_metrics()
    gpu_info = get_gpu_info()
    disks = get_disk_usage()
    top_procs = get_top_processes(sort_by="cpu", limit=10)
    services = get_services_grouped()
    ports = get_listening_ports()
    docker_containers = get_docker_containers()

    # Merge GPU info (names, memory) into gpu_metrics
    gpu_info_map = {g["index"]: g for g in gpu_info}
    enriched_gpus = []
    for gm in gpu_metrics:
        gi = gpu_info_map.get(gm["index"], {})
        enriched_gpus.append({
            **gm,
            "name": gi.get("name", ""),
            "memory_total_mb": gi.get("memory_total_mb"),
            "memory_used_mb": gi.get("memory_used_mb"),
        })

    # Running services count
    running_services = services.get("running", [])
    failed_services = services.get("failed", [])

    return {
        # CPU
        "cpu_usage": get_cpu_usage(),
        "cpu_temperature": get_cpu_temperature(),
        # GPU
        "gpu_metrics": enriched_gpus,
        "gpu_usage": gpu_metrics[0]["gpu_usage_percent"] if gpu_metrics else None,
        "gpu_temperature": gpu_metrics[0]["temperature_c"] if gpu_metrics else None,
        # RAM
        "ram_total": mem["total"],
        "ram_used": mem["used"],
        "ram_percent": mem["percent"],
        # Network
        "network_bytes_sent": net["bytes_sent"],
        "network_bytes_recv": net["bytes_recv"],
        # Disks — send ALL partitions
        "disks": disks,
        "disk_total": disks[0].get("total", 0) if disks else 0,
        "disk_used": disks[0].get("used", 0) if disks else 0,
        "disk_percent": disks[0].get("percent", 0) if disks else 0,
        # Top processes
        "top_processes": top_procs,
        # Services summary
        "running_services": [{"name": s["name"], "sub_state": s["sub_state"]} for s in running_services[:30]],
        "failed_services": [{"name": s["name"], "sub_state": s["sub_state"]} for s in failed_services],
        "services_running_count": len(running_services),
        "services_failed_count": len(failed_services),
        # Docker containers
        "docker_containers": docker_containers,
        "docker_running_count": sum(1 for c in docker_containers if c.get("state") == "running"),
        "docker_total_count": len(docker_containers),
        # Listening ports
        "listening_ports": ports,
        # Ollama models (for AI orchestrator)
        "ollama_models": get_ollama_models(),
        # Riffusion models (audio generation)
        "riffusion_models": get_riffusion_models(config.riffusion_url),
        # GPU services (MusicGen, Bark, RVC)
        "musicgen_models": get_musicgen_models(config.musicgen_url),
        "bark_models": get_bark_models(config.bark_url),
        "rvc_models": get_rvc_models(config.rvc_url),
        "coqui_tts_models": get_coqui_tts_models(config.coqui_tts_url),
        "stt_models": get_stt_models(config.stt_url),
        "ltx_video_models": get_ltx_video_models(config.ltx_video_url),
        "wan_video_models": get_wan_video_models(config.wan_video_url),
        # ComfyUI liveness — dict or None. Bob-api auto-registers a comfyui
        # provider for this agent's host when this field is non-null. Works
        # whether ComfyUI is dockerized or a host process.
        "comfyui_status": get_comfyui_status(config.comfyui_url),
        # Script runner scripts (for GPU tools)
        "script_runner_scripts": get_script_runner_scripts(config.script_runner_url),
        "script_runner_port": _get_script_runner_port(),
        # Agent host for script runner resolution
        "agent_host": _get_local_ip(),
        # Agent version
        "agent_version": agent_version,
    }


def _get_script_runner_port() -> int:
    """Extract port from script runner URL."""
    from urllib.parse import urlparse
    parsed = urlparse(config.script_runner_url)
    return parsed.port or 9101


def _get_local_ip() -> str:
    """Get the local network IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"
