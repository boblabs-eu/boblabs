"""Bob Manager Agent — Prometheus metrics exporter.

Exposes a /metrics HTTP endpoint for Prometheus scraping.
"""

import logging

from aiohttp import web
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Gauge,
    generate_latest,
)

from app.collectors.cpu import get_cpu_temperature, get_cpu_usage
from app.collectors.disk import get_disk_usage
from app.collectors.gpu import get_gpu_info, get_gpu_metrics
from app.collectors.memory import get_memory_usage
from app.collectors.network import get_network_io

logger = logging.getLogger(__name__)

# Custom registry to avoid default Python metrics
registry = CollectorRegistry()

# ── Gauges ───────────────────────────────────────
cpu_usage_gauge = Gauge("bob_cpu_usage_percent", "CPU usage percentage", registry=registry)
cpu_temp_gauge = Gauge("bob_cpu_temperature_celsius", "CPU temperature", registry=registry)

ram_total_gauge = Gauge("bob_ram_total_bytes", "Total RAM", registry=registry)
ram_used_gauge = Gauge("bob_ram_used_bytes", "Used RAM", registry=registry)
ram_percent_gauge = Gauge("bob_ram_usage_percent", "RAM usage percentage", registry=registry)

gpu_usage_gauge = Gauge(
    "bob_gpu_usage_percent", "GPU utilization", ["gpu_index"], registry=registry
)
gpu_temp_gauge = Gauge(
    "bob_gpu_temperature_celsius", "GPU temperature", ["gpu_index"], registry=registry
)
gpu_mem_used_gauge = Gauge(
    "bob_gpu_memory_used_mb", "GPU memory used", ["gpu_index"], registry=registry
)
gpu_power_gauge = Gauge(
    "bob_gpu_power_draw_watts", "GPU power draw", ["gpu_index"], registry=registry
)

net_sent_gauge = Gauge("bob_network_bytes_sent", "Network bytes sent", registry=registry)
net_recv_gauge = Gauge("bob_network_bytes_recv", "Network bytes received", registry=registry)

disk_usage_gauge = Gauge(
    "bob_disk_usage_percent", "Disk usage percentage", ["mountpoint"], registry=registry
)


def update_metrics() -> None:
    """Collect fresh metrics and update Prometheus gauges."""
    # CPU
    cpu_usage_gauge.set(get_cpu_usage())
    temp = get_cpu_temperature()
    if temp is not None:
        cpu_temp_gauge.set(temp)

    # RAM
    mem = get_memory_usage()
    ram_total_gauge.set(mem["total"])
    ram_used_gauge.set(mem["used"])
    ram_percent_gauge.set(mem["percent"])

    # GPU
    for gpu in get_gpu_metrics():
        idx = str(gpu["index"])
        if gpu["gpu_usage_percent"] is not None:
            gpu_usage_gauge.labels(gpu_index=idx).set(gpu["gpu_usage_percent"])
        if gpu["temperature_c"] is not None:
            gpu_temp_gauge.labels(gpu_index=idx).set(gpu["temperature_c"])
        if gpu.get("power_draw_w") is not None:
            gpu_power_gauge.labels(gpu_index=idx).set(gpu["power_draw_w"])

    gpu_info = get_gpu_info()
    for gpu in gpu_info:
        idx = str(gpu["index"])
        gpu_mem_used_gauge.labels(gpu_index=idx).set(gpu["memory_used_mb"])

    # Network
    net = get_network_io()
    net_sent_gauge.set(net["bytes_sent"])
    net_recv_gauge.set(net["bytes_recv"])

    # Disk
    for disk in get_disk_usage():
        disk_usage_gauge.labels(mountpoint=disk["mountpoint"]).set(disk["percent"])


async def metrics_handler(request: web.Request) -> web.Response:
    """HTTP handler for /metrics endpoint."""
    update_metrics()
    return web.Response(
        body=generate_latest(registry),
        content_type=CONTENT_TYPE_LATEST,
    )


async def start_metrics_server(port: int) -> web.AppRunner:
    """Start the Prometheus metrics HTTP server."""
    app = web.Application()
    app.router.add_get("/metrics", metrics_handler)
    app.router.add_get("/health", lambda r: web.json_response({"status": "ok"}))

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("Metrics server started on port %d", port)
    return runner
