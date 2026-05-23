#!/usr/bin/env bash
# Bob Script Runner — Install & setup as systemd service
# Run on each GPU server that has models installed.
#
# Usage: sudo bash install.sh
#
set -euo pipefail

SCRIPTS_DIR="${BOB_SCRIPTS_DIR:-/opt/bob-scripts}"
RUNNER_DIR="/opt/bob-script-runner"
VENV_DIR="$RUNNER_DIR/venv"
SERVICE_PORT="${BOB_SCRIPTS_PORT:-9101}"

echo "=== Bob Script Runner Installer ==="

# 1. Create directories
mkdir -p "$SCRIPTS_DIR" "$RUNNER_DIR"

# 2. Copy runner files
cp main.py requirements.txt "$RUNNER_DIR/"

# 2b. Copy bundled scripts (won't overwrite customized local copies)
if [ -d "scripts" ]; then
    for script in scripts/*.py; do
        [ -f "$script" ] || continue
        base="$(basename "$script")"
        if [ ! -f "$SCRIPTS_DIR/$base" ]; then
            cp "$script" "$SCRIPTS_DIR/"
            echo "  Installed new script: $base"
        else
            # Update existing scripts to get latest metadata / fixes
            cp "$script" "$SCRIPTS_DIR/$base"
            echo "  Updated script: $base"
        fi
    done
fi

# 3. Create venv & install deps
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$RUNNER_DIR/requirements.txt"

# 4. Create systemd service
cat > /etc/systemd/system/bob-script-runner.service <<EOF
[Unit]
Description=Bob Script Runner (GPU model execution)
After=network.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$RUNNER_DIR
Environment=BOB_SCRIPTS_DIR=$SCRIPTS_DIR
Environment=BOB_SCRIPTS_PORT=$SERVICE_PORT
Environment=BOB_SCRIPTS_OUTPUT=/tmp/bob-script-output
Environment=BOB_SCRIPTS_MAX_OUTPUT_MB=100
Environment=HF_TOKEN=${HF_TOKEN:-}
ExecStart=$VENV_DIR/bin/python main.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# 5. Enable and start
systemctl daemon-reload
systemctl enable bob-script-runner
systemctl start bob-script-runner

echo ""
echo "=== Installed ==="
echo "  Service:    bob-script-runner"
echo "  Port:       $SERVICE_PORT"
echo "  Scripts:    $SCRIPTS_DIR"
echo "  Status:     systemctl status bob-script-runner"
echo ""
echo "Drop .py scripts in $SCRIPTS_DIR and they'll be auto-discovered."
