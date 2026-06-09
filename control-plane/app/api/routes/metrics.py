"""Bob Manager — Metrics API routes."""

from fastapi import APIRouter, Depends

from app.services.authorization import require_infra_access
from app.services.metrics_service import MetricsService

# CSO #1 + #2 — the cached agent metrics payload (~100 KB per fleet) leaks
# every GPU server's hostname, hardware inventory, CPU/GPU usage history,
# disk mounts, network throughput. Pre-fix the router had no auth and
# nginx proxied /api/ to the public internet, so the whole fleet recon
# surface was world-readable. Gate the router with require_infra_access
# (mirroring commands.py / servers.py which expose the same class of
# operator-only surface). Closes both the collection route and the
# per-server variant in a single dependency.
router = APIRouter(
    prefix="/metrics",
    tags=["metrics"],
    dependencies=[Depends(require_infra_access)],
)


@router.get("")
async def get_all_metrics():
    """Return all cached agent metrics."""
    svc = MetricsService()
    return svc.get_all_metrics()


@router.get("/{server_name}")
async def get_server_metrics(server_name: str):
    """Return cached metrics for a specific server."""
    svc = MetricsService()
    metrics = svc.get_server_metrics(server_name)
    if metrics is None:
        return {"detail": "No metrics available for this server"}
    return metrics
