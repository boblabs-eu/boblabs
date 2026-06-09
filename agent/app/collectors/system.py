"""Bob Manager Agent — System info collector."""

import logging
import platform
import subprocess

logger = logging.getLogger(__name__)


def get_os_info() -> dict:
    """Return operating system information."""
    return {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "hostname": platform.node(),
        "python_version": platform.python_version(),
        "linux_distro": _get_linux_distro(),
    }


def get_software_versions() -> dict:
    """Return installed software versions."""
    return {
        "nvidia_driver": _run_cmd("nvidia-smi --query-gpu=driver_version --format=csv,noheader"),
        "cuda_version": _get_cuda_version(),
        "rust_version": _run_cmd("rustc --version"),
        "cargo_version": _run_cmd("cargo --version"),
        "docker_version": _run_cmd("docker --version"),
        "python_version": platform.python_version(),
    }


def _get_linux_distro() -> str:
    """Read /etc/os-release for distro info."""
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except FileNotFoundError:
        # Try host mount
        try:
            with open("/host/etc/os-release") as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        return line.split("=", 1)[1].strip().strip('"')
        except FileNotFoundError:
            pass
    return platform.platform()


def _get_cuda_version() -> str | None:
    """Get CUDA version from nvidia-smi."""
    try:
        result = subprocess.run(
            ["nvidia-smi"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        for line in result.stdout.splitlines():
            if "CUDA Version" in line:
                parts = line.split("CUDA Version:")
                if len(parts) > 1:
                    return parts[1].strip().rstrip("|").strip()
    except Exception:
        pass
    return None


def _run_cmd(cmd: str) -> str | None:
    """Run a shell command and return stdout or None."""
    try:
        result = subprocess.run(
            cmd.split(),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None
