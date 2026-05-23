"""Bob Manager — Admin observability endpoints.

Exposes the data backing the /admin/logs UI: HTTP request log table,
filterable lists, and a metrics summary for the dashboard cards/charts.

All routes require role == "admin" (see `require_admin`).
"""

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text

from app.api.dependencies import DbSession, require_admin

router = APIRouter(prefix="/admin/logs", tags=["admin-logs"])


SinceShort = Literal["15m", "1h", "6h", "24h", "7d", "30d"]
_SINCE_TO_DELTA: dict[str, timedelta] = {
    "15m": timedelta(minutes=15),
    "1h":  timedelta(hours=1),
    "6h":  timedelta(hours=6),
    "24h": timedelta(days=1),
    "7d":  timedelta(days=7),
    "30d": timedelta(days=30),
}


def _since_to_dt(since: str) -> datetime:
    delta = _SINCE_TO_DELTA.get(since)
    if delta is None:
        raise HTTPException(400, f"invalid 'since' value: {since}")
    return datetime.now(timezone.utc) - delta


# ── Filtered request list ──────────────────────────────


@router.get("/requests")
async def list_request_logs(
    db: DbSession,
    _admin: dict = Depends(require_admin),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    since: SinceShort = "24h",
    module: str | None = None,
    severity: Literal["info", "warn", "error"] | None = None,
    user_email: str | None = None,
    ip: str | None = None,
    method: str | None = None,
    status_code: int | None = Query(None, ge=100, le=599, alias="status"),
    search: str | None = None,
):
    """Return paginated request_log rows with the active filters applied."""
    where = ["timestamp >= :since"]
    params: dict = {"since": _since_to_dt(since)}
    if module:
        where.append("module = :module"); params["module"] = module
    if severity:
        where.append("severity = :severity"); params["severity"] = severity
    if user_email:
        where.append("user_email = :user_email"); params["user_email"] = user_email
    if ip:
        where.append("ip = :ip"); params["ip"] = ip
    if method:
        where.append("method = :method"); params["method"] = method.upper()
    if status_code is not None:
        where.append("status = :status_code"); params["status_code"] = status_code
    if search:
        where.append("(path ILIKE :search OR query ILIKE :search OR error_msg ILIKE :search)")
        params["search"] = f"%{search}%"
    clause = " AND ".join(where)

    rows_q = text(
        f"SELECT id, timestamp, ip, method, path, query, status, duration_ms, "
        f"       user_email, user_role, user_agent, referer, module, severity, error_msg "
        f"FROM request_log WHERE {clause} "
        f"ORDER BY timestamp DESC LIMIT :limit OFFSET :offset"
    )
    count_q = text(f"SELECT COUNT(*) AS c FROM request_log WHERE {clause}")

    rows_res = await db.execute(rows_q, {**params, "limit": limit, "offset": offset})
    count_res = await db.execute(count_q, params)

    items = [
        {
            "id":          str(r.id),
            "timestamp":   r.timestamp.isoformat(),
            "ip":          r.ip,
            "method":      r.method,
            "path":        r.path,
            "query":       r.query,
            "status":      r.status,
            "duration_ms": r.duration_ms,
            "user_email":  r.user_email,
            "user_role":   r.user_role,
            "user_agent":  r.user_agent,
            "referer":     r.referer,
            "module":      r.module,
            "severity":    r.severity,
            "error_msg":   r.error_msg,
        }
        for r in rows_res.fetchall()
    ]
    total = int(count_res.scalar() or 0)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


# ── Distinct values (for filter dropdowns) ──────────────


@router.get("/facets")
async def request_log_facets(
    db: DbSession,
    _admin: dict = Depends(require_admin),
    since: SinceShort = "24h",
):
    """Return distinct modules / users / IPs in the time window."""
    since_dt = _since_to_dt(since)
    modules = await db.execute(text(
        "SELECT module, COUNT(*) AS c FROM request_log "
        "WHERE timestamp >= :since GROUP BY module ORDER BY c DESC"
    ), {"since": since_dt})
    users = await db.execute(text(
        "SELECT user_email, COUNT(*) AS c FROM request_log "
        "WHERE timestamp >= :since AND user_email IS NOT NULL "
        "GROUP BY user_email ORDER BY c DESC LIMIT 50"
    ), {"since": since_dt})
    ips = await db.execute(text(
        "SELECT ip, COUNT(*) AS c FROM request_log "
        "WHERE timestamp >= :since AND ip IS NOT NULL "
        "GROUP BY ip ORDER BY c DESC LIMIT 50"
    ), {"since": since_dt})
    return {
        "modules": [{"value": r.module, "count": int(r.c)} for r in modules.fetchall()],
        "users":   [{"value": r.user_email, "count": int(r.c)} for r in users.fetchall()],
        "ips":     [{"value": r.ip, "count": int(r.c)} for r in ips.fetchall()],
    }


# ── Dashboard metrics (cards + charts) ──────────────────


@router.get("/metrics")
async def request_log_metrics(
    db: DbSession,
    _admin: dict = Depends(require_admin),
    since: SinceShort = "24h",
):
    """Aggregate counts/percentiles/timeseries to feed the dashboard."""
    since_dt = _since_to_dt(since)
    bucket_minutes = {"15m": 1, "1h": 5, "6h": 15, "24h": 30, "7d": 240, "30d": 1440}[since]
    p = {"since": since_dt}

    totals_res = await db.execute(text(
        "SELECT "
        "  COUNT(*)                                            AS total, "
        "  COUNT(*) FILTER (WHERE severity = 'error')          AS errors, "
        "  COUNT(*) FILTER (WHERE severity = 'warn')           AS warns, "
        "  COUNT(DISTINCT ip)                                  AS unique_ips, "
        "  COUNT(DISTINCT user_email) FILTER (WHERE user_email IS NOT NULL) AS unique_users, "
        "  ROUND(AVG(duration_ms)::numeric, 1)                 AS avg_ms, "
        "  PERCENTILE_DISC(0.5) WITHIN GROUP (ORDER BY duration_ms) AS p50_ms, "
        "  PERCENTILE_DISC(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_ms "
        "FROM request_log WHERE timestamp >= :since"
    ), p)
    t = totals_res.fetchone()

    bucket_seconds = bucket_minutes * 60
    timeseries_res = await db.execute(text(
        "SELECT to_timestamp("
        f"         FLOOR(EXTRACT(EPOCH FROM timestamp) / {bucket_seconds}) * {bucket_seconds}"
        "       ) AS bucket, "
        "       COUNT(*)                                      AS total, "
        "       COUNT(*) FILTER (WHERE severity = 'error')    AS errors "
        "FROM request_log WHERE timestamp >= :since "
        "GROUP BY bucket ORDER BY bucket ASC"
    ), p)

    by_module_res = await db.execute(text(
        "SELECT module, COUNT(*) AS c FROM request_log "
        "WHERE timestamp >= :since GROUP BY module ORDER BY c DESC"
    ), p)
    by_status_res = await db.execute(text(
        "SELECT (status / 100) * 100 AS bucket, COUNT(*) AS c FROM request_log "
        "WHERE timestamp >= :since GROUP BY bucket ORDER BY bucket ASC"
    ), p)
    top_paths_res = await db.execute(text(
        "SELECT path, COUNT(*) AS c FROM request_log "
        "WHERE timestamp >= :since GROUP BY path ORDER BY c DESC LIMIT 10"
    ), p)
    top_users_res = await db.execute(text(
        "SELECT user_email, COUNT(*) AS c FROM request_log "
        "WHERE timestamp >= :since AND user_email IS NOT NULL "
        "GROUP BY user_email ORDER BY c DESC LIMIT 10"
    ), p)
    top_ips_res = await db.execute(text(
        "SELECT ip, COUNT(*) AS c FROM request_log "
        "WHERE timestamp >= :since AND ip IS NOT NULL "
        "GROUP BY ip ORDER BY c DESC LIMIT 10"
    ), p)
    recent_errors_res = await db.execute(text(
        "SELECT timestamp, method, path, status, user_email, ip, error_msg "
        "FROM request_log WHERE timestamp >= :since AND severity = 'error' "
        "ORDER BY timestamp DESC LIMIT 20"
    ), p)

    return {
        "since": since,
        "bucket_minutes": bucket_minutes,
        "totals": {
            "total":        int(t.total or 0),
            "errors":       int(t.errors or 0),
            "warns":        int(t.warns or 0),
            "unique_ips":   int(t.unique_ips or 0),
            "unique_users": int(t.unique_users or 0),
            "avg_ms":       float(t.avg_ms or 0),
            "p50_ms":       int(t.p50_ms or 0),
            "p95_ms":       int(t.p95_ms or 0),
        },
        "timeseries": [
            {"bucket": r.bucket.isoformat(), "total": int(r.total), "errors": int(r.errors)}
            for r in timeseries_res.fetchall()
        ],
        "by_module": [{"module": r.module, "count": int(r.c)} for r in by_module_res.fetchall()],
        "by_status": [{"bucket": int(r.bucket), "count": int(r.c)} for r in by_status_res.fetchall()],
        "top_paths": [{"path": r.path, "count": int(r.c)} for r in top_paths_res.fetchall()],
        "top_users": [{"user_email": r.user_email, "count": int(r.c)} for r in top_users_res.fetchall()],
        "top_ips":   [{"ip": r.ip, "count": int(r.c)} for r in top_ips_res.fetchall()],
        "recent_errors": [
            {
                "timestamp":  r.timestamp.isoformat(),
                "method":     r.method,
                "path":       r.path,
                "status":     int(r.status),
                "user_email": r.user_email,
                "ip":         r.ip,
                "error_msg":  r.error_msg,
            }
            for r in recent_errors_res.fetchall()
        ],
    }


# ── Pass-through wrappers (gated by admin) ──────────────


@router.get("/lab-loops")
async def list_lab_loop_events(
    db: DbSession,
    _admin: dict = Depends(require_admin),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    severity: str | None = None,
):
    where = ["1=1"]
    p: dict = {}
    if severity:
        where.append("severity = :severity"); p["severity"] = severity
    res = await db.execute(text(
        "SELECT id, lab_id, severity, score, signals, removed_count, recovered, detected_at "
        f"FROM lab_loop_events WHERE {' AND '.join(where)} "
        "ORDER BY detected_at DESC LIMIT :limit OFFSET :offset"
    ), {**p, "limit": limit, "offset": offset})
    return [
        {
            "id":            str(r.id),
            "lab_id":        str(r.lab_id),
            "severity":      r.severity,
            "score":         int(r.score),
            "signals":       r.signals,
            "removed_count": int(r.removed_count),
            "recovered":     bool(r.recovered),
            "detected_at":   r.detected_at.isoformat(),
        }
        for r in res.fetchall()
    ]


@router.get("/tasks")
async def list_orchestrator_tasks(
    db: DbSession,
    _admin: dict = Depends(require_admin),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    status_filter: str | None = Query(None, alias="status"),
):
    where = ["1=1"]
    p: dict = {}
    if status_filter:
        where.append("status = :status"); p["status"] = status_filter
    res = await db.execute(text(
        "SELECT id, conversation_id, task_type, status, priority, "
        "       queued_at, started_at, completed_at, error "
        f"FROM orchestrator_tasks WHERE {' AND '.join(where)} "
        "ORDER BY queued_at DESC LIMIT :limit OFFSET :offset"
    ), {**p, "limit": limit, "offset": offset})
    return [
        {
            "id":              str(r.id),
            "conversation_id": str(r.conversation_id) if r.conversation_id else None,
            "task_type":       r.task_type,
            "status":          r.status,
            "priority":        int(r.priority) if r.priority is not None else None,
            "queued_at":       r.queued_at.isoformat() if r.queued_at else None,
            "started_at":      r.started_at.isoformat() if r.started_at else None,
            "completed_at":    r.completed_at.isoformat() if r.completed_at else None,
            "error":           r.error,
        }
        for r in res.fetchall()
    ]
