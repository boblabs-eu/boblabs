"""Bob Manager Agent — UFW Firewall inspector."""

import logging
import subprocess

logger = logging.getLogger(__name__)


def get_firewall_status() -> dict:
    """Return UFW firewall status and rules."""
    status = {
        "active": False,
        "rules": [],
    }

    try:
        result = subprocess.run(
            ["ufw", "status", "verbose"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            logger.warning("ufw status failed: %s", result.stderr)
            return status

        lines = result.stdout.splitlines()
        for line in lines:
            if line.startswith("Status:"):
                status["active"] = "active" in line.lower()
            elif line.startswith("Default:"):
                status["default_policy"] = line.split(":", 1)[1].strip()
            elif "--" not in line and line.strip() and not line.startswith("To"):
                # Parse rule lines
                parts = line.split()
                if len(parts) >= 3:
                    status["rules"].append(
                        {
                            "to": parts[0],
                            "action": parts[1],
                            "from": parts[2] if len(parts) > 2 else "Anywhere",
                            "raw": line.strip(),
                        }
                    )

    except FileNotFoundError:
        status["error"] = "ufw not installed"
    except Exception as e:
        status["error"] = str(e)

    return status
