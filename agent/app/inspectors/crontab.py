"""Bob Manager Agent — Crontab inspector."""

import subprocess
import logging

logger = logging.getLogger(__name__)


def get_crontabs() -> list[dict]:
    """Return all cron jobs for all users.

    Returns list of dicts with: user, schedule, command.
    """
    jobs = []

    # Current user crontab
    jobs.extend(_get_user_crontab("root"))

    # System crontab (/etc/crontab)
    jobs.extend(_get_system_crontab())

    # Check /etc/cron.d
    jobs.extend(_get_cron_d())

    return jobs


def _get_user_crontab(user: str = "") -> list[dict]:
    """Get crontab for a specific user or current user."""
    try:
        cmd = ["crontab", "-l"]
        if user:
            cmd = ["crontab", "-l", "-u", user]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return []

        return _parse_crontab(result.stdout, user or "current")
    except Exception:
        return []


def _get_system_crontab() -> list[dict]:
    """Parse /etc/crontab."""
    try:
        with open("/etc/crontab") as f:
            content = f.read()
        return _parse_crontab(content, "system")
    except FileNotFoundError:
        try:
            with open("/host/etc/crontab") as f:
                content = f.read()
            return _parse_crontab(content, "system")
        except FileNotFoundError:
            return []


def _get_cron_d() -> list[dict]:
    """Parse files in /etc/cron.d/."""
    import os

    jobs = []
    cron_dir = "/etc/cron.d"
    if not os.path.exists(cron_dir):
        cron_dir = "/host/etc/cron.d"

    try:
        for fname in os.listdir(cron_dir):
            fpath = os.path.join(cron_dir, fname)
            if os.path.isfile(fpath):
                with open(fpath) as f:
                    jobs.extend(_parse_crontab(f.read(), f"cron.d/{fname}"))
    except (FileNotFoundError, PermissionError):
        pass

    return jobs


def _parse_crontab(content: str, source: str) -> list[dict]:
    """Parse crontab content into structured entries."""
    jobs = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("@"):
            # Special schedule syntax
            parts = line.split(None, 1)
            if len(parts) == 2:
                jobs.append({
                    "source": source,
                    "schedule": parts[0],
                    "command": parts[1],
                })
        else:
            parts = line.split(None, 5)
            if len(parts) >= 6:
                jobs.append({
                    "source": source,
                    "schedule": " ".join(parts[:5]),
                    "command": parts[5],
                })
    return jobs
