"""Bob Manager Agent — GPU metrics collector (NVIDIA)."""

import json
import subprocess
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _run_nvidia_smi(*args: str) -> str | None:
    """Run nvidia-smi with given arguments and return stdout."""
    try:
        result = subprocess.run(
            ["nvidia-smi", *args],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except FileNotFoundError:
        logger.debug("nvidia-smi not found")
    except Exception as e:
        logger.warning("nvidia-smi error: %s", e)
    return None


def get_gpu_info() -> list[dict[str, Any]]:
    """Return GPU information for all GPUs."""
    output = _run_nvidia_smi(
        "--query-gpu=index,name,driver_version,memory.total,memory.used,memory.free",
        "--format=csv,noheader,nounits",
    )
    if output is None:
        return []

    gpus = []
    for line in output.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 6:
            gpus.append({
                "index": int(parts[0]),
                "name": parts[1],
                "driver_version": parts[2],
                "memory_total_mb": int(parts[3]),
                "memory_used_mb": int(parts[4]),
                "memory_free_mb": int(parts[5]),
            })
    return gpus


def get_gpu_metrics() -> list[dict[str, Any]]:
    """Return GPU usage metrics for all GPUs."""
    output = _run_nvidia_smi(
        "--query-gpu=index,utilization.gpu,utilization.memory,temperature.gpu,power.draw,power.limit",
        "--format=csv,noheader,nounits",
    )
    if output is None:
        return []

    metrics = []
    for line in output.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 6:
            metrics.append({
                "index": int(parts[0]),
                "gpu_usage_percent": _safe_float(parts[1]),
                "memory_usage_percent": _safe_float(parts[2]),
                "temperature_c": _safe_float(parts[3]),
                "power_draw_w": _safe_float(parts[4]),
                "power_limit_w": _safe_float(parts[5]),
            })
    return metrics


def get_gpu_processes() -> list[dict]:
    """Return processes using the GPU."""
    output = _run_nvidia_smi(
        "--query-compute-apps=pid,process_name,used_memory",
        "--format=csv,noheader,nounits",
    )
    if output is None:
        return []

    processes = []
    for line in output.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3:
            processes.append({
                "pid": int(parts[0]),
                "process_name": parts[1],
                "gpu_memory_mb": int(parts[2]),
            })
    return processes


def get_nvidia_driver_version() -> str | None:
    """Return the NVIDIA driver version string."""
    output = _run_nvidia_smi("--query-gpu=driver_version", "--format=csv,noheader")
    if output:
        return output.splitlines()[0].strip()
    return None


def _safe_float(val: str) -> float | None:
    """Parse a float, returning None on failure."""
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
