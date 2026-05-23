"""Bob Manager Agent — Process inspector."""

import psutil


def get_top_processes(sort_by: str = "cpu", limit: int = 30) -> list[dict]:
    """Return top processes sorted by resource usage.

    Args:
        sort_by: 'cpu', 'memory', or 'name'.
        limit: Maximum number of processes to return.

    Returns:
        List of process dicts with PID, name, CPU%, memory%, command.
    """
    processes = []
    for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "cmdline", "username"]):
        try:
            info = proc.info
            processes.append({
                "pid": info["pid"],
                "name": info["name"],
                "cpu_percent": info["cpu_percent"] or 0.0,
                "memory_percent": round(info["memory_percent"] or 0.0, 2),
                "command": " ".join(info["cmdline"]) if info["cmdline"] else info["name"],
                "username": info["username"],
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # Sort
    if sort_by == "cpu":
        processes.sort(key=lambda p: p["cpu_percent"], reverse=True)
    elif sort_by == "memory":
        processes.sort(key=lambda p: p["memory_percent"], reverse=True)
    else:
        processes.sort(key=lambda p: p["name"].lower())

    return processes[:limit]
