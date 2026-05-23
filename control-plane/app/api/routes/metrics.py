"""Bob Manager — Metrics API routes."""

from fastapi import APIRouter

from app.services.metrics_service import MetricsService

router = APIRouter(prefix="/metrics", tags=["metrics"])


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
