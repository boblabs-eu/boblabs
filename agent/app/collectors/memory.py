"""Bob Manager Agent — Memory metrics collector."""

import psutil


def get_memory_usage() -> dict:
    """Return RAM usage statistics."""
    mem = psutil.virtual_memory()
    return {
        "total": mem.total,
        "used": mem.used,
        "available": mem.available,
        "percent": mem.percent,
    }


def get_swap_usage() -> dict:
    """Return swap usage statistics."""
    swap = psutil.swap_memory()
    return {
        "total": swap.total,
        "used": swap.used,
        "free": swap.free,
        "percent": swap.percent,
    }
