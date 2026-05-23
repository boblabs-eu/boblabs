#!/usr/bin/env bash
# Bob Manager Agent — Host install script
# Run on each GPU server: sudo bash install.sh
#
# Prerequisites: Python 3.10+, pip
set -euo pipefail

INSTALL_DIR="/opt/bob-agent"
SERVICE_NAME="bob-agent"
ENV_FILE="/etc/bob-agent.env"

# Default — overridden by .env if it exists
AGENT_USER="bob-agent"

echo "=== Bob Manager Agent Installer ==="

# ── Check root ────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    echo "Error: Run this script as root (sudo bash install.sh)"
    exit 1
fi

# ── Load AGENT_USER from env file if it exists ────
if [[ -f "$ENV_FILE" ]]; then
    # Source only AGENT_USER to avoid polluting the shell
    _user=$(grep -E '^AGENT_USER=' "$ENV_FILE" | tail -1 | cut -d= -f2- || true)
    if [[ -n "$_user" ]]; then
        AGENT_USER="$_user"
    fi
fi
echo "Service user: $AGENT_USER"

# ── Check Python ──────────────────────────────────
PYTHON=""
for cmd in python3.12 python3.11 python3.10 python3; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done

if [[ -z "$PYTHON" ]]; then
    echo "Error: Python 3.10+ is required. Install with: sudo apt install python3 python3-pip python3-venv"
    exit 1
fi

echo "Using Python: $PYTHON ($($PYTHON --version))"

# ── Create / update service user ──────────────────
if ! id "$AGENT_USER" &>/dev/null; then
    useradd --system --create-home --shell /bin/bash "$AGENT_USER"
    echo "Created system user: $AGENT_USER"
else
    # Ensure existing user has a login shell (needed for PTY terminal)
    current_shell=$(getent passwd "$AGENT_USER" | cut -d: -f7)
    if [[ "$current_shell" == */nologin || "$current_shell" == */false ]]; then
        usermod --shell /bin/bash "$AGENT_USER"
        echo "Updated $AGENT_USER shell to /bin/bash"
    fi
fi

# Add to required groups for monitoring
usermod -aG video "$AGENT_USER"  2>/dev/null || true   # nvidia-smi
usermod -aG docker "$AGENT_USER" 2>/dev/null || true   # docker ps/stats/inspect
echo "Groups for $AGENT_USER: $(id -nG "$AGENT_USER")"

# ── Install files ─────────────────────────────────
echo "Installing to $INSTALL_DIR ..."
mkdir -p "$INSTALL_DIR"
# Remove stale Python bytecode before copying
find app -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
rm -rf "$INSTALL_DIR/app/__pycache__" "$INSTALL_DIR/app"/*/__pycache__ 2>/dev/null || true
cp -r app "$INSTALL_DIR/"
cp requirements.txt "$INSTALL_DIR/"
chown -R "$AGENT_USER:$AGENT_USER" "$INSTALL_DIR"

# ── Create venv & install deps ────────────────────
echo "Setting up Python virtual environment..."
$PYTHON -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip -q
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" -q
echo "Dependencies installed."

# ── Create env file if missing ────────────────────
if [[ ! -f "$ENV_FILE" ]]; then
    cat > "$ENV_FILE" <<EOF
# Bob Manager Agent configuration
# Edit these values for your setup

# System user the agent runs as (needs docker + video groups)
AGENT_USER=${AGENT_USER}

AGENT_NAME=gpu-server
CONTROL_PLANE_URL=ws://YOUR_CONTROL_PLANE_IP:8888/ws/agent
# Comma-separated for multiple control planes:
# CONTROL_PLANE_URL=ws://PROD_IP:8888/ws/agent,ws://DEV_IP:8888/ws/agent
AGENT_SECRET=change-this-to-a-random-secret-token
METRICS_PORT=9100
HEARTBEAT_INTERVAL=30
METRICS_INTERVAL=10
EOF
    chmod 600 "$ENV_FILE"
    echo ""
    echo "*** IMPORTANT: Edit $ENV_FILE with your settings ***"
    echo "    - Set AGENT_USER to the user the agent should run as"
    echo "    - Set AGENT_NAME to a unique name for this server"
    echo "    - Set CONTROL_PLANE_URL to your control plane address (comma-separated for multiple)"
    echo "    - Set AGENT_SECRET to match the control plane secret"
    echo ""
else
    # Ensure AGENT_USER is present in existing env file
    if ! grep -q '^AGENT_USER=' "$ENV_FILE"; then
        sed -i "1i # System user the agent runs as\nAGENT_USER=${AGENT_USER}\n" "$ENV_FILE"
        echo "Added AGENT_USER=$AGENT_USER to $ENV_FILE"
    fi
fi

# ── Install systemd service ──────────────────────
echo "Installing systemd service..."
cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=Bob Manager Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${AGENT_USER}
Group=${AGENT_USER}
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${INSTALL_DIR}/venv/bin/python -m app.main
Restart=always
RestartSec=5

# Security hardening
ProtectSystem=false
NoNewPrivileges=false

# Allow GPU + Docker access
SupplementaryGroups=video docker

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

echo ""
echo "=== Installation complete ==="
echo ""
echo "Agent will run as: $AGENT_USER"
echo "Groups: $(id -nG "$AGENT_USER")"
echo ""
echo "Next steps:"
echo "  1. Edit /etc/bob-agent.env with your settings"
echo "     (set AGENT_USER, AGENT_NAME, CONTROL_PLANE_URL, AGENT_SECRET)"
echo "  2. Start the agent:  sudo systemctl start bob-agent"
echo "  3. Check status:     sudo systemctl status bob-agent"
echo "  4. View logs:        sudo journalctl -u bob-agent -f"
echo ""
