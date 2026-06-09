"""Bob Manager Agent — Disk metrics collector."""

import psutil


def get_disk_usage() -> list[dict]:
    """Return disk usage for all mounted partitions."""
    partitions = psutil.disk_partitions()
    disks = []
    for p in partitions:
        try:
            usage = psutil.disk_usage(p.mountpoint)
            disks.append(
                {
                    "device": p.device,
                    "mountpoint": p.mountpoint,
                    "fstype": p.fstype,
                    "total": usage.total,
                    "used": usage.used,
                    "free": usage.free,
                    "percent": usage.percent,
                }
            )
        except (PermissionError, OSError):
            continue
    return disks


def get_disk_io() -> dict:
    """Return disk I/O counters."""
    try:
        io = psutil.disk_io_counters()
        if io is None:
            return {}
        return {
            "read_bytes": io.read_bytes,
            "write_bytes": io.write_bytes,
            "read_count": io.read_count,
            "write_count": io.write_count,
        }
    except Exception:
        return {}
