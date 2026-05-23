#!/usr/bin/env bash
# Bob ComfyUI — Install ComfyUI as a systemd unit on a GPU host.
#
# ComfyUI is shipped as a host install (not Docker) because each deployment
# brings its own model zoo (checkpoints, LoRAs, VAEs, ControlNets, ...).
# Models are operator-managed under <install-dir>/models/.
#
# After install:
#   1. Drop checkpoints into <install-dir>/models/checkpoints/
#   2. In Bob UI, register an AI Provider:
#        Type:     comfyui
#        Base URL: http://<this-host>:<port>
#   3. The existing tool_comfyui.py will route through it.
#
# Usage:
#   sudo bash install.sh                                    # default install
#   sudo bash install.sh --port 8188 --cuda 12.1
#   sudo bash install.sh --install-dir /opt/comfyui --ref master
#   sudo bash install.sh --uninstall                        # keep models
#   sudo bash install.sh --uninstall --purge                # also wipe install-dir
#
set -euo pipefail

# ── Defaults ─────────────────────────────────────────

PORT=8188
INSTALL_DIR=/opt/comfyui
GIT_REF=master
CUDA_VARIANT=cu121
SERVICE_USER=comfyui
REPO_URL=https://github.com/comfyanonymous/ComfyUI.git
SERVICE_NAME=bob-comfyui
MODE=install
PURGE=false

# ── Arg parsing ──────────────────────────────────────

usage() {
    cat <<EOF
Usage: sudo bash install.sh [options]

Options:
  --port PORT          Listen port (default: 8188)
  --install-dir DIR    Install directory (default: /opt/comfyui)
  --ref REF            Git ref/branch/tag to checkout (default: master)
  --cuda VARIANT       PyTorch CUDA wheel: cu121 | cu124 | cu128 (default: cu121)
  --user USER          System user to run service as (default: comfyui)
  --uninstall          Stop + disable + remove systemd unit
  --purge              With --uninstall: also rm -rf install-dir (DESTROYS MODELS)
  -h | --help          Show this help

Examples:
  sudo bash install.sh
  sudo bash install.sh --port 8190 --cuda cu124
  sudo bash install.sh --uninstall
  sudo bash install.sh --uninstall --purge
EOF
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --port)         PORT="$2"; shift 2 ;;
        --install-dir)  INSTALL_DIR="$2"; shift 2 ;;
        --ref)          GIT_REF="$2"; shift 2 ;;
        --cuda)         CUDA_VARIANT="$2"; shift 2 ;;
        --user)         SERVICE_USER="$2"; shift 2 ;;
        --uninstall)    MODE=uninstall; shift ;;
        --purge)        PURGE=true; shift ;;
        -h|--help)      usage ;;
        *) echo "Unknown arg: $1"; usage ;;
    esac
done

VENV_DIR="${INSTALL_DIR}/venv"
UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

# ── Helpers ──────────────────────────────────────────

need_root() {
    if [[ $EUID -ne 0 ]]; then
        echo "Error: must be run as root (sudo)."
        exit 1
    fi
}

torch_index_for_cuda() {
    case "$CUDA_VARIANT" in
        cu121) echo "https://download.pytorch.org/whl/cu121" ;;
        cu124) echo "https://download.pytorch.org/whl/cu124" ;;
        cu128) echo "https://download.pytorch.org/whl/cu128" ;;
        *)     echo "Unknown --cuda variant: $CUDA_VARIANT (use cu121|cu124|cu128)" >&2; exit 1 ;;
    esac
}

# ── Install ──────────────────────────────────────────

install_comfyui() {
    echo "=== Installing ${SERVICE_NAME} ==="
    echo "  Port:        ${PORT}"
    echo "  Install dir: ${INSTALL_DIR}"
    echo "  Git ref:     ${GIT_REF}"
    echo "  CUDA wheel:  ${CUDA_VARIANT}"
    echo "  Run as user: ${SERVICE_USER}"

    # 1. System deps
    echo "  Installing system dependencies..."
    apt-get update -qq
    apt-get install -y -qq \
        git python3-venv python3-dev build-essential \
        ffmpeg libgl1 libglib2.0-0 curl ca-certificates >/dev/null

    # 2. Service user
    if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
        echo "  Creating system user: ${SERVICE_USER}"
        useradd --system --shell /usr/sbin/nologin --home-dir "$INSTALL_DIR" "$SERVICE_USER"
    fi

    # 3. Clone repo
    if [[ ! -d "${INSTALL_DIR}/.git" ]]; then
        echo "  Cloning ComfyUI..."
        mkdir -p "$(dirname "$INSTALL_DIR")"
        git clone "$REPO_URL" "$INSTALL_DIR"
    else
        echo "  Repo exists, fetching latest..."
        git -C "$INSTALL_DIR" fetch --all --tags --prune
    fi
    echo "  Checking out ${GIT_REF}..."
    git -C "$INSTALL_DIR" checkout "$GIT_REF"
    git -C "$INSTALL_DIR" pull --ff-only origin "$GIT_REF" || true

    # 4. Venv + deps
    if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
        echo "  Creating Python venv..."
        python3 -m venv "$VENV_DIR"
    fi
    echo "  Upgrading pip..."
    "${VENV_DIR}/bin/pip" install --upgrade pip wheel -q

    local torch_index
    torch_index="$(torch_index_for_cuda)"
    echo "  Installing PyTorch (${CUDA_VARIANT})..."
    "${VENV_DIR}/bin/pip" install --upgrade \
        torch torchvision torchaudio --index-url "$torch_index" -q

    echo "  Installing ComfyUI requirements..."
    "${VENV_DIR}/bin/pip" install -r "${INSTALL_DIR}/requirements.txt" -q

    # 5. Models directory tree (operator drops files in)
    echo "  Ensuring models directory layout..."
    for sub in checkpoints loras vae controlnet embeddings clip_vision upscale_models; do
        mkdir -p "${INSTALL_DIR}/models/${sub}"
    done
    mkdir -p "${INSTALL_DIR}/input" "${INSTALL_DIR}/output" "${INSTALL_DIR}/temp"

    # 6. Ownership
    echo "  Setting ownership to ${SERVICE_USER}..."
    chown -R "${SERVICE_USER}:${SERVICE_USER}" "$INSTALL_DIR"

    # 7. Systemd unit
    echo "  Writing systemd unit: ${UNIT_FILE}"
    cat > "$UNIT_FILE" <<EOF
[Unit]
Description=Bob ComfyUI server (host install)
After=network.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_USER}
WorkingDirectory=${INSTALL_DIR}
Environment=PYTHONUNBUFFERED=1
ExecStart=${VENV_DIR}/bin/python main.py --listen 0.0.0.0 --port ${PORT}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable "${SERVICE_NAME}" >/dev/null
    systemctl restart "${SERVICE_NAME}"

    echo ""
    echo "=== Done ==="
    echo "  Service:  ${SERVICE_NAME}"
    echo "  URL:      http://0.0.0.0:${PORT}"
    echo "  Status:   systemctl status ${SERVICE_NAME}"
    echo "  Logs:     journalctl -u ${SERVICE_NAME} -f"
    echo ""
    echo "Next steps:"
    echo "  1. Drop checkpoints into ${INSTALL_DIR}/models/checkpoints/"
    echo "  2. In Bob UI → Settings → AI Providers, add:"
    echo "       Type:     comfyui"
    echo "       Base URL: http://<this-host>:${PORT}"
    echo "  3. Test with the comfyui_test.lab.json blueprint."
}

# ── Uninstall ────────────────────────────────────────

uninstall_comfyui() {
    echo "=== Uninstalling ${SERVICE_NAME} ==="

    if systemctl is-active --quiet "${SERVICE_NAME}" 2>/dev/null; then
        systemctl stop "${SERVICE_NAME}"
        echo "  Stopped ${SERVICE_NAME}"
    fi

    if systemctl is-enabled --quiet "${SERVICE_NAME}" 2>/dev/null; then
        systemctl disable "${SERVICE_NAME}" >/dev/null
        echo "  Disabled ${SERVICE_NAME}"
    fi

    if [[ -f "$UNIT_FILE" ]]; then
        rm -f "$UNIT_FILE"
        systemctl daemon-reload
        echo "  Removed systemd unit"
    fi

    if [[ "$PURGE" == "true" ]]; then
        if [[ -d "$INSTALL_DIR" ]]; then
            echo "  --purge: removing ${INSTALL_DIR} (including models)"
            rm -rf "$INSTALL_DIR"
        fi
        if id -u "$SERVICE_USER" >/dev/null 2>&1; then
            userdel "$SERVICE_USER" 2>/dev/null || true
            echo "  Removed user ${SERVICE_USER}"
        fi
    else
        echo "  Kept ${INSTALL_DIR} (use --purge to delete it and its models)"
    fi

    echo "  Done"
}

# ── Main ─────────────────────────────────────────────

need_root
case "$MODE" in
    install)   install_comfyui ;;
    uninstall) uninstall_comfyui ;;
esac
