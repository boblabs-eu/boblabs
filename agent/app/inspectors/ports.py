"""Bob Manager Agent — Port inspector."""

import psutil


def get_listening_ports() -> list[dict]:
    """Return all listening ports with associated process info."""
    ports = []
    try:
        connections = psutil.net_connections(kind="inet")
        for conn in connections:
            if conn.status == "LISTEN" and conn.laddr:
                proc_info = _get_process_info(conn.pid)
                ports.append({
                    "port": conn.laddr.port,
                    "address": conn.laddr.ip,
                    "pid": conn.pid,
                    "process": proc_info.get("name", "unknown"),
                    "command": proc_info.get("command", ""),
                })
    except (psutil.AccessDenied, PermissionError):
        pass

    # Deduplicate by port
    seen = set()
    unique = []
    for p in ports:
        if p["port"] not in seen:
            seen.add(p["port"])
            unique.append(p)

    return sorted(unique, key=lambda x: x["port"])


def _get_process_info(pid: int | None) -> dict:
    """Get process name and command by PID."""
    if pid is None:
        return {"name": "unknown", "command": ""}
    try:
        proc = psutil.Process(pid)
        cmdline = proc.cmdline()
        return {
            "name": proc.name(),
            "command": " ".join(cmdline) if cmdline else proc.name(),
        }
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return {"name": "unknown", "command": ""}
