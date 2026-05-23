#!/usr/bin/env bash
# Bob Manager Agent — Uninstall script
set -euo pipefail

SERVICE_NAME="bob-agent"
INSTALL_DIR="/opt/bob-agent"

if [[ $EUID -ne 0 ]]; then
    echo "Error: Run as root (sudo bash uninstall.sh)"
    exit 1
fi

echo "Stopping bob-agent..."
systemctl stop "$SERVICE_NAME" 2>/dev/null || true
systemctl disable "$SERVICE_NAME" 2>/dev/null || true
rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
systemctl daemon-reload

echo "Removing $INSTALL_DIR ..."
rm -rf "$INSTALL_DIR"

echo "Note: /etc/bob-agent.env was NOT removed (contains your config)."
echo "      Remove it manually if desired: sudo rm /etc/bob-agent.env"
echo ""
echo "Agent uninstalled."
