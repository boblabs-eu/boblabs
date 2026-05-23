"""Bob Manager Agent — Network metrics collector."""

import psutil


def get_network_io() -> dict:
    """Return network I/O statistics."""
    net = psutil.net_io_counters()
    return {
        "bytes_sent": net.bytes_sent,
        "bytes_recv": net.bytes_recv,
        "packets_sent": net.packets_sent,
        "packets_recv": net.packets_recv,
        "errin": net.errin,
        "errout": net.errout,
    }


def get_network_interfaces() -> dict:
    """Return network interface addresses."""
    addrs = psutil.net_if_addrs()
    result = {}
    for iface, addr_list in addrs.items():
        result[iface] = []
        for addr in addr_list:
            result[iface].append({
                "family": str(addr.family),
                "address": addr.address,
                "netmask": addr.netmask,
            })
    return result


def get_connections() -> list[dict]:
    """Return active network connections."""
    try:
        connections = psutil.net_connections(kind="inet")
        return [
            {
                "fd": c.fd,
                "family": str(c.family),
                "type": str(c.type),
                "local_addr": f"{c.laddr.ip}:{c.laddr.port}" if c.laddr else None,
                "remote_addr": f"{c.raddr.ip}:{c.raddr.port}" if c.raddr else None,
                "status": c.status,
                "pid": c.pid,
            }
            for c in connections[:100]  # Limit to avoid huge payloads
        ]
    except (psutil.AccessDenied, PermissionError):
        return []
