#!/usr/bin/env bash
# Bob GPU Services — Install one or more services as systemd units.
#
# Installs each service into /opt/bob-<service>/ with its own venv.
# Models load on first request, unload after idle timeout.
#
# Usage:
#   sudo bash install.sh musicgen          # Install just MusicGen
#   sudo bash install.sh bark              # Install just Bark
#   sudo bash install.sh rvc               # Install just RVC
#   sudo bash install.sh all               # Install all three
#   sudo bash install.sh musicgen bark     # Install specific services
#
# Uninstall:
#   sudo bash install.sh --uninstall musicgen
#   sudo bash install.sh --uninstall all
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Service definitions ──────────────────────────────

declare -A SVC_PORT=(
    [musicgen]=3014
    [bark]=3015
    [rvc]=3016
    [stt]=7865
    [ltx-video]=3018
)

declare -A SVC_DIR_NAME=(
    [musicgen]=musicgen-api
    [bark]=bark-api
    [rvc]=rvc-api
    [stt]=stt-api
    [ltx-video]=ltx-video-api
)

declare -A SVC_DESCRIPTION=(
    [musicgen]="Bob MusicGen API (text-to-music)"
    [bark]="Bob Bark API (text-to-speech/singing)"
    [rvc]="Bob RVC API (voice conversion)"
    [stt]="Bob STT API (speech-to-text, Whisper)"
    [ltx-video]="Bob LTX-Video API (text/image-to-video, LTX-2.3)"
)

declare -A SVC_ENV_PREFIX=(
    [musicgen]=MUSICGEN
    [bark]=BARK
    [rvc]=RVC
    [stt]=STT
    [ltx-video]=LTX
)

ALL_SERVICES=(musicgen bark rvc stt ltx-video)

# ── Helpers ──────────────────────────────────────────

usage() {
    echo "Usage: sudo bash install.sh [--uninstall] <service|all> [service ...]"
    echo ""
    echo "Services: musicgen, bark, rvc, stt, ltx-video, all"
    exit 1
}

need_root() {
    if [[ $EUID -ne 0 ]]; then
        echo "Error: This script must be run as root (sudo)."
        exit 1
    fi
}

parse_services() {
    local services=()
    for arg in "$@"; do
        if [[ "$arg" == "all" ]]; then
            services=("${ALL_SERVICES[@]}")
            break
        elif [[ -v "SVC_PORT[$arg]" ]]; then
            services+=("$arg")
        else
            echo "Unknown service: $arg"
            usage
        fi
    done
    echo "${services[@]}"
}

# ── Install a single service ────────────────────────

install_service() {
    local svc="$1"
    local port="${SVC_PORT[$svc]}"
    local dir_name="${SVC_DIR_NAME[$svc]}"
    local description="${SVC_DESCRIPTION[$svc]}"
    local env_prefix="${SVC_ENV_PREFIX[$svc]}"
    local install_dir="/opt/bob-${dir_name}"
    local venv_dir="${install_dir}/venv"
    local service_name="bob-${dir_name}"
    local source_dir="${SCRIPT_DIR}/${dir_name}"

    echo ""
    echo "=== Installing ${service_name} ==="

    # Validate source exists
    if [[ ! -f "${source_dir}/app.py" ]]; then
        echo "Error: ${source_dir}/app.py not found"
        return 1
    fi

    # 0. Install system build dependencies
    echo "  Installing system dependencies..."
    apt-get update -qq
    if [[ "$svc" == "musicgen" ]]; then
        apt-get install -y -qq python3-dev python3-venv ffmpeg \
            pkg-config libavformat-dev libavcodec-dev libavdevice-dev \
            libavutil-dev libswscale-dev libswresample-dev libavfilter-dev >/dev/null
    elif [[ "$svc" == "rvc" ]]; then
        apt-get install -y -qq python3-dev python3-venv ffmpeg build-essential >/dev/null
    elif [[ "$svc" == "stt" ]]; then
        apt-get install -y -qq python3-dev python3-venv ffmpeg >/dev/null
    elif [[ "$svc" == "ltx-video" ]]; then
        apt-get install -y -qq python3-dev python3-venv ffmpeg git curl >/dev/null
    else
        apt-get install -y -qq python3-dev python3-venv ffmpeg >/dev/null
    fi

    # 1. Create install dir
    mkdir -p "$install_dir"

    # 2. Copy files
    cp "${source_dir}/app.py" "${install_dir}/"
    cp "${source_dir}/requirements.txt" "${install_dir}/"
    # Copy additional module files if present
    for extra in "${source_dir}"/*.py; do
        [[ "$(basename "$extra")" == "app.py" ]] && continue
        cp "$extra" "${install_dir}/"
    done

    # 3. RVC: create models directory
    if [[ "$svc" == "rvc" ]]; then
        local models_dir="${RVC_MODELS_DIR:-/opt/bob-rvc-models}"
        mkdir -p "$models_dir"
        echo "  RVC models directory: $models_dir"
    fi

    # 4. Create venv & install deps
    echo "  Creating Python venv..."
    python3 -m venv "$venv_dir"
    "${venv_dir}/bin/pip" install --upgrade pip uv -q

    if [[ "$svc" == "ltx-video" ]]; then
        # LTX-Video requires LTX-2 monorepo packages + PyTorch ~=2.7 + CUDA 12.8
        local ltx_repo="${install_dir}/ltx-2"
        if [[ ! -d "${ltx_repo}/packages" ]]; then
            echo "  Cloning LTX-2 repo..."
            git clone --depth 1 https://github.com/Lightricks/LTX-2.git "$ltx_repo"
        else
            echo "  LTX-2 repo already cloned, pulling updates..."
            git -C "$ltx_repo" pull --ff-only || true
        fi
        echo "  Installing numpy<2 first (torch compat)..."
        "${venv_dir}/bin/uv" pip install --python "${venv_dir}/bin/python" --no-cache 'numpy<2'
        echo "  Installing PyTorch 2.7 with CUDA 12.8 support..."
        "${venv_dir}/bin/uv" pip install --python "${venv_dir}/bin/python" --no-cache \
            'torch~=2.7.0' 'torchaudio~=2.7.0' --index-url https://download.pytorch.org/whl/cu128
        echo "  Installing LTX-2 packages (ltx-core, ltx-pipelines)..."
        "${venv_dir}/bin/uv" pip install --python "${venv_dir}/bin/python" --no-cache \
            "${ltx_repo}/packages/ltx-core" "${ltx_repo}/packages/ltx-pipelines"
        echo "  Installing API dependencies..."
        "${venv_dir}/bin/uv" pip install --python "${venv_dir}/bin/python" --no-cache \
            -r "${install_dir}/requirements.txt"
    else
        echo "  Installing numpy<2 first (torch compat)..."
        "${venv_dir}/bin/uv" pip install --python "${venv_dir}/bin/python" --no-cache 'numpy<2'
        echo "  Installing PyTorch with CUDA support..."
        "${venv_dir}/bin/uv" pip install --python "${venv_dir}/bin/python" --no-cache torch torchaudio --index-url https://download.pytorch.org/whl/cu121
        echo "  Installing dependencies..."
        "${venv_dir}/bin/uv" pip install --python "${venv_dir}/bin/python" --no-cache -r "${install_dir}/requirements.txt" \
            --extra-index-url https://download.pytorch.org/whl/cu121
    fi

    # 5. Build environment lines for systemd
    local env_lines=""
    env_lines+="Environment=${env_prefix}_HOST=0.0.0.0\n"
    env_lines+="Environment=${env_prefix}_PORT=${port}\n"
    env_lines+="Environment=HF_TOKEN=${HF_TOKEN:-}\n"

    if [[ "$svc" == "musicgen" ]]; then
        env_lines+="Environment=MUSICGEN_MODEL=${MUSICGEN_MODEL:-medium}\n"
        env_lines+="Environment=MUSICGEN_MAX_DURATION_SEC=${MUSICGEN_MAX_DURATION_SEC:-30}\n"
        env_lines+="Environment=MUSICGEN_IDLE_UNLOAD_SEC=${MUSICGEN_IDLE_UNLOAD_SEC:-300}\n"
    elif [[ "$svc" == "bark" ]]; then
        env_lines+="Environment=BARK_IDLE_UNLOAD_SEC=${BARK_IDLE_UNLOAD_SEC:-300}\n"
        env_lines+="Environment=BARK_MAX_TEXT_LENGTH=${BARK_MAX_TEXT_LENGTH:-2000}\n"
    elif [[ "$svc" == "rvc" ]]; then
        local rvc_models="${RVC_MODELS_DIR:-/opt/bob-rvc-models}"
        env_lines+="Environment=RVC_MODELS_DIR=${rvc_models}\n"
        env_lines+="Environment=RVC_IDLE_UNLOAD_SEC=${RVC_IDLE_UNLOAD_SEC:-300}\n"
    elif [[ "$svc" == "stt" ]]; then
        env_lines+="Environment=STT_MODEL_SIZE=${STT_MODEL_SIZE:-large-v3}\n"
        env_lines+="Environment=STT_COMPUTE_TYPE=${STT_COMPUTE_TYPE:-float16}\n"
        env_lines+="Environment=STT_IDLE_UNLOAD_SEC=${STT_IDLE_UNLOAD_SEC:-300}\n"
        env_lines+="Environment=STT_MAX_FILE_SIZE_MB=${STT_MAX_FILE_SIZE_MB:-500}\n"
    elif [[ "$svc" == "ltx-video" ]]; then
        local ltx_models="${LTX_MODELS_DIR:-/opt/bob-ltx-video-models}"
        mkdir -p "$ltx_models"
        env_lines+="Environment=LTX_PIPELINE_MODE=${LTX_PIPELINE_MODE:-distilled}\n"
        env_lines+="Environment=LTX_QUANTIZATION=${LTX_QUANTIZATION:-fp8-cast}\n"
        env_lines+="Environment=LTX_IDLE_UNLOAD_SEC=${LTX_IDLE_UNLOAD_SEC:-600}\n"
        env_lines+="Environment=LTX_CHECKPOINT_PATH=${ltx_models}/${LTX_CHECKPOINT:-ltx-2.3-22b-distilled-1.1.safetensors}\n"
        env_lines+="Environment=LTX_UPSAMPLER_PATH=${ltx_models}/${LTX_UPSAMPLER:-ltx-2.3-spatial-upscaler-x2-1.1.safetensors}\n"
        env_lines+="Environment=LTX_DISTILLED_LORA_PATH=${ltx_models}/${LTX_DISTILLED_LORA:-ltx-2.3-22b-distilled-lora-384-1.1.safetensors}\n"
        env_lines+="Environment=LTX_GEMMA_ROOT=${LTX_GEMMA_ROOT:-${ltx_models}/gemma}\n"
        env_lines+="Environment=PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True\n"
        echo "  LTX-Video models directory: $ltx_models"
        echo "  Download models: huggingface-cli download Lightricks/LTX-2.3 --include '*.safetensors' --local-dir ${ltx_models}"
        echo "  Download Gemma:  huggingface-cli download google/gemma-3-12b-it-qat-q4_0-unquantized --local-dir ${ltx_models}/gemma"
    fi

    # 6. Create systemd service
    cat > "/etc/systemd/system/${service_name}.service" <<EOF
[Unit]
Description=${description}
After=network.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=${install_dir}
$(echo -e "$env_lines")ExecStart=${venv_dir}/bin/python app.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    # 7. Enable and start
    systemctl daemon-reload
    systemctl enable "${service_name}"
    systemctl start "${service_name}"

    echo "  Service:  ${service_name}"
    echo "  Port:     ${port}"
    echo "  Dir:      ${install_dir}"
    echo "  Status:   systemctl status ${service_name}"
    echo "  Logs:     journalctl -u ${service_name} -f"
}

# ── Uninstall a single service ──────────────────────

uninstall_service() {
    local svc="$1"
    local dir_name="${SVC_DIR_NAME[$svc]}"
    local service_name="bob-${dir_name}"
    local install_dir="/opt/bob-${dir_name}"

    echo ""
    echo "=== Uninstalling ${service_name} ==="

    if systemctl is-active --quiet "${service_name}" 2>/dev/null; then
        systemctl stop "${service_name}"
        echo "  Stopped ${service_name}"
    fi

    if systemctl is-enabled --quiet "${service_name}" 2>/dev/null; then
        systemctl disable "${service_name}"
        echo "  Disabled ${service_name}"
    fi

    if [[ -f "/etc/systemd/system/${service_name}.service" ]]; then
        rm "/etc/systemd/system/${service_name}.service"
        systemctl daemon-reload
        echo "  Removed systemd unit"
    fi

    if [[ -d "$install_dir" ]]; then
        rm -rf "$install_dir"
        echo "  Removed ${install_dir}"
    fi

    echo "  Done"
}

# ── Main ─────────────────────────────────────────────

main() {
    need_root

    if [[ $# -lt 1 ]]; then
        usage
    fi

    local mode="install"
    local args=("$@")

    if [[ "${args[0]}" == "--uninstall" ]]; then
        mode="uninstall"
        args=("${args[@]:1}")
    fi

    if [[ ${#args[@]} -lt 1 ]]; then
        usage
    fi

    local services
    read -ra services <<< "$(parse_services "${args[@]}")"

    echo "=== Bob GPU Services ${mode^} ==="
    echo "  Services: ${services[*]}"

    for svc in "${services[@]}"; do
        if [[ "$mode" == "install" ]]; then
            install_service "$svc"
        else
            uninstall_service "$svc"
        fi
    done

    echo ""
    echo "=== ${mode^} complete ==="
}

main "$@"
