"""Bob Manager Agent — CPU metrics collector."""

import psutil


def get_cpu_usage() -> float:
    """Return overall CPU usage percentage."""
    return psutil.cpu_percent(interval=1)


def get_cpu_per_core() -> list[float]:
    """Return CPU usage per core."""
    return psutil.cpu_percent(interval=1, percpu=True)


def get_cpu_temperature() -> float | None:
    """Return CPU temperature in Celsius.

    Returns None if sensor data is unavailable.
    """
    try:
        temps = psutil.sensors_temperatures()
        if not temps:
            return None

        # Try common sensor names
        for name in ("coretemp", "k10temp", "cpu_thermal", "cpu-thermal"):
            if name in temps:
                entries = temps[name]
                if entries:
                    return entries[0].current
        # Fallback: first available
        for entries in temps.values():
            if entries:
                return entries[0].current
    except Exception:
        pass
    return None


def get_cpu_info() -> dict:
    """Return CPU information summary."""
    return {
        "physical_cores": psutil.cpu_count(logical=False),
        "logical_cores": psutil.cpu_count(logical=True),
        "frequency_mhz": psutil.cpu_freq().current if psutil.cpu_freq() else None,
    }
