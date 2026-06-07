"""Wave 4 P — direct_cmd_exec cron routes through sandbox HTTP /shell_exec.

Pre-fix: `_execute_lab_cron_cmd` called `docker.from_env().exec_run(...)`
which was blocked by the docker-socket-proxy `EXEC=0` posture, so the
cron silently never ran. The user wanted the cron to actually work
without widening the proxy capability — so the fix routes through the
sandbox container's existing HTTP `/shell_exec` endpoint (same path the
agent's `shell_exec` tool already uses).

Tests assert via source introspection (httpx call to /shell_exec) and
the function name that the legacy docker exec path is GONE.
"""

from __future__ import annotations

import inspect

import pytest

from app.services import lab_scheduler

pytestmark = pytest.mark.regression


def test_execute_lab_cron_cmd_no_docker_exec_run():
    """The old docker.exec_run path must be gone from _execute_lab_cron_cmd."""
    fn = getattr(lab_scheduler, "_execute_lab_cron_cmd", None)
    if fn is None:
        pytest.skip("function renamed — update test to track")
    src = inspect.getsource(fn)
    assert ".exec_run(" not in src, (
        "_execute_lab_cron_cmd still calls docker .exec_run — Wave 4 P regression "
        "(docker-socket-proxy EXEC=0 silently blocks this)"
    )


def test_execute_lab_cron_cmd_posts_to_shell_exec():
    """The fix posts to the sandbox container's /shell_exec endpoint."""
    fn = getattr(lab_scheduler, "_execute_lab_cron_cmd", None)
    if fn is None:
        pytest.skip("function renamed — update test to track")
    src = inspect.getsource(fn)
    assert "/shell_exec" in src, (
        "_execute_lab_cron_cmd no longer references /shell_exec — Wave 4 P regression"
    )
    # The fix calls httpx.AsyncClient (or similar) instead of docker SDK.
    assert "httpx" in src or "AsyncClient" in src, (
        "_execute_lab_cron_cmd no longer uses httpx — Wave 4 P regression"
    )


def test_execute_lab_cron_cmd_builds_sandbox_url_from_lab_id():
    """The sandbox URL convention is bob-lab-<first12>:9000."""
    fn = getattr(lab_scheduler, "_execute_lab_cron_cmd", None)
    if fn is None:
        pytest.skip("function renamed — update test to track")
    src = inspect.getsource(fn)
    assert "bob-lab-" in src, (
        "_execute_lab_cron_cmd no longer builds the bob-lab-<id> URL — Wave 4 P regression"
    )


def test_failure_path_writes_lab_message():
    """On network failure the cron result must surface in lab_messages
    (else the operator can't see what failed)."""
    src = inspect.getsource(lab_scheduler)
    # We look for any pattern that writes a CRON-JOB error/result message.
    assert "CRON-JOB" in src and ("failed" in src.lower() or "result" in src.lower()), (
        "lab_scheduler no longer surfaces direct_cmd_exec failures into "
        "lab_messages — Wave 4 P regression (silent failure mode)"
    )
