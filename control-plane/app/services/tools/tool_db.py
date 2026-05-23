"""SQLite database tools: db_query, db_execute, db_schema."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from app.services.tool_executor import ToolExecutor

logger = logging.getLogger(__name__)

TOOLS = {
    "db_query": {
        "description": (
            "Execute a read-only SQL query (SELECT) on the agent's SQLite database "
            "and return rows with column names. Use db_schema first to discover tables."
        ),
        "parameters": {
            "sql": {"type": "string", "description": "SQL SELECT query to execute", "required": True},
            "params": {
                "type": "array",
                "description": "Optional list of bind parameters for ? placeholders",
                "required": False,
            },
        },
    },
    "db_execute": {
        "description": (
            "Execute a write SQL statement (CREATE TABLE, INSERT, UPDATE, DELETE) "
            "on the agent's SQLite database. Returns affected row count."
        ),
        "parameters": {
            "sql": {"type": "string", "description": "SQL statement to execute", "required": True},
            "params": {
                "type": "array",
                "description": "Optional list of bind parameters for ? placeholders",
                "required": False,
            },
        },
    },
    "db_schema": {
        "description": (
            "Show the schema of the agent's SQLite database: tables, columns, "
            "types, and row counts. Call this to discover what data is available."
        ),
        "parameters": {},
    },
}


async def db_query(executor: ToolExecutor, args: dict) -> dict:
    sql = args.get("sql", "").strip()
    if not sql:
        return {"success": False, "output": "db_query requires 'sql'"}

    params = args.get("params") or []

    try:
        sandbox_url = await executor.get_sandbox_url()
        async with httpx.AsyncClient(timeout=executor.timeout_sec + 5) as client:
            resp = await client.post(f"{sandbox_url}/db_query", json={
                "lab_id": str(executor.lab_id),
                "sql": sql,
                "params": params,
                "timeout_sec": executor.timeout_sec,
                "max_output_kb": executor.max_output_bytes // 1024,
            })
            return resp.json()
    except httpx.TimeoutException:
        return {"success": False, "output": f"DB query timed out after {executor.timeout_sec}s"}
    except Exception as e:
        logger.exception("db_query failed for lab %s", executor.lab_id)
        return {"success": False, "output": f"Sandbox error: {e}"}


async def db_execute(executor: ToolExecutor, args: dict) -> dict:
    sql = args.get("sql", "").strip()
    if not sql:
        return {"success": False, "output": "db_execute requires 'sql'"}

    params = args.get("params") or []

    try:
        sandbox_url = await executor.get_sandbox_url()
        async with httpx.AsyncClient(timeout=executor.timeout_sec + 5) as client:
            resp = await client.post(f"{sandbox_url}/db_execute", json={
                "lab_id": str(executor.lab_id),
                "sql": sql,
                "params": params,
                "timeout_sec": executor.timeout_sec,
                "max_output_kb": executor.max_output_bytes // 1024,
            })
            return resp.json()
    except httpx.TimeoutException:
        return {"success": False, "output": f"DB execute timed out after {executor.timeout_sec}s"}
    except Exception as e:
        logger.exception("db_execute failed for lab %s", executor.lab_id)
        return {"success": False, "output": f"Sandbox error: {e}"}


async def db_schema(executor: ToolExecutor, args: dict) -> dict:
    try:
        sandbox_url = await executor.get_sandbox_url()
        async with httpx.AsyncClient(timeout=executor.timeout_sec + 5) as client:
            resp = await client.post(f"{sandbox_url}/db_schema", json={
                "lab_id": str(executor.lab_id),
                "timeout_sec": executor.timeout_sec,
                "max_output_kb": executor.max_output_bytes // 1024,
            })
            return resp.json()
    except httpx.TimeoutException:
        return {"success": False, "output": f"DB schema timed out after {executor.timeout_sec}s"}
    except Exception as e:
        logger.exception("db_schema failed for lab %s", executor.lab_id)
        return {"success": False, "output": f"Sandbox error: {e}"}


HANDLERS = {
    "db_query": db_query,
    "db_execute": db_execute,
    "db_schema": db_schema,
}
