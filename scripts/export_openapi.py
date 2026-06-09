#!/usr/bin/env python3
"""Export the control-plane FastAPI OpenAPI spec to stdout as sorted JSON.

The artifact at docs/openapi.json is the authoritative public-API contract
(see VERSIONING.md). Regenerate it after any route change:

    python scripts/export_openapi.py > docs/openapi.json

The diff between this output and docs/openapi.json is the CI drift gate
(scripts/check_openapi_drift.sh).

Run requirements:
    pip install -r control-plane/requirements.txt

The script sets safe defaults for env vars the control-plane reads at
import time so `app.main` can be imported without a live database, JWT
key, or single-worker lock.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


def _bootstrap_env() -> None:
    """Populate the minimum env the control-plane reads at import."""
    os.environ.setdefault("BOB_API_ALLOW_MULTI_WORKER", "1")
    os.environ.setdefault(
        "BOB_API_LOCK_PATH",
        str(Path(tempfile.gettempdir()) / "bob-api.openapi-export.lock"),
    )
    os.environ.setdefault(
        "DATABASE_URL",
        "postgresql+asyncpg://stub:stub@localhost:5432/stub",
    )
    os.environ.setdefault("JWT_SECRET", "openapi-export-stub-secret")
    os.environ.setdefault("ADMIN_SECRET", "openapi-export-stub-secret")
    os.environ.setdefault("AGENT_SECRET", "openapi-export-stub-secret")


def main() -> int:
    _bootstrap_env()
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "control-plane"))

    # pydantic_settings.BaseSettings auto-loads .env from CWD. If we're
    # invoked from the repo root, /repo/.env contains operator fields
    # the Settings class doesn't model and pydantic raises "extra
    # inputs not permitted". Chdir to a directory without a .env so
    # only our stub env vars (set above) are consumed.
    os.chdir(tempfile.gettempdir())

    try:
        from app.main import app
    except Exception as exc:  # noqa: BLE001 — surface any import failure
        sys.stderr.write(
            f"Failed to import control-plane FastAPI app: {exc!r}\n"
            f"Did you `pip install -r control-plane/requirements.txt`?\n"
        )
        return 1

    spec = app.openapi()
    json.dump(spec, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
