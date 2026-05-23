# ComfyUI (host install)

ComfyUI is installed directly on the GPU host (not Docker) because each deployment ships its own model zoo (checkpoints, LoRAs, VAEs, ControlNets, ...). Models are operator-managed under `<install-dir>/models/`.

The control plane already ships the `comfyui` tool ([control-plane/app/services/tools/tool_comfyui.py](../../control-plane/app/services/tools/tool_comfyui.py)). This installer only stands up the upstream server it talks to.

## Install

```bash
# Default: port 8188, /opt/comfyui, master, cu121
sudo bash install.sh

# Custom port + CUDA wheel
sudo bash install.sh --port 8190 --cuda cu124

# Pin to a specific git ref
sudo bash install.sh --ref v0.3.10
```

Options:

| Flag            | Default       | Description                                 |
|-----------------|---------------|---------------------------------------------|
| `--port`        | `8188`        | Listen port                                 |
| `--install-dir` | `/opt/comfyui`| Install root                                |
| `--ref`         | `master`      | Git ref / branch / tag                      |
| `--cuda`        | `cu121`       | PyTorch wheel: `cu121` \| `cu124` \| `cu128`|
| `--user`        | `comfyui`     | System user that runs the service           |

## Post-install

1. Drop model files into the right subfolder:
   - `<install-dir>/models/checkpoints/` (SD 1.5, SDXL, SD3, Flux, ...)
   - `<install-dir>/models/loras/`
   - `<install-dir>/models/vae/`
   - `<install-dir>/models/controlnet/`
   - `<install-dir>/models/embeddings/`
2. In **Bob UI → Settings → AI Providers**, add a provider:
   - **Type**: `comfyui`
   - **Base URL**: `http://<this-host>:<port>`
3. Run [templates/lab_examples/comfyui_test.lab.json](../../templates/lab_examples/comfyui_test.lab.json) to verify the round-trip.

## Manage

```bash
systemctl status bob-comfyui
journalctl -u bob-comfyui -f
sudo systemctl restart bob-comfyui
```

## Uninstall

```bash
# Stop + remove unit, keep install-dir (and models)
sudo bash install.sh --uninstall

# Also wipe /opt/comfyui (DESTROYS MODELS)
sudo bash install.sh --uninstall --purge
```
