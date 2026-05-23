# Citations & Attributions

Third-party works used in or referenced by this project. Bob Manager itself is
released under Apache 2.0 (see [LICENSE](LICENSE) and [NOTICE](NOTICE)); each
work below keeps its original license.

---

## Software

### ComfyUI

Node-based UI and execution backend for Stable Diffusion / Flux / LTX-Video and
similar diffusion pipelines. Bob Manager ships a built-in `comfyui` tool, a
host-side installer, and direct dispatchers for Flux text-to-image and LTX
image-to-video.

- **Repository:** <https://github.com/comfyanonymous/ComfyUI>
- **License:** GPL-3.0
- **Used in:**
  - [`gpu-services/comfyui/`](gpu-services/comfyui/) — host installer and operator README
  - [`control-plane/app/services/tools/tool_comfyui.py`](control-plane/app/services/tools/tool_comfyui.py) — agent-facing tool
  - [`control-plane/app/api/routes/internal_apps.py`](control-plane/app/api/routes/internal_apps.py) — `comfyui_dispatch`, `comfyui_flux_text2img`, `comfyui_ltx_image2video` endpoints
  - [`templates/comfyui/`](templates/comfyui/) — preset workflow JSONs (Flux text-to-image, LTX-2.3 image-to-video)

### Remotion

React-based programmatic video rendering. Bob Manager runs a `bob-remotion`
sidecar that exposes a small HTTP API for rendering MP4s from JSX
compositions.

- **Repository:** <https://github.com/remotion-dev/remotion>
- **License:** [Remotion License](https://remotion.dev/license) — free for
  individuals and companies with up to 3 employees; larger organizations need a
  commercial license. **Operators are responsible for ensuring their use is
  compliant.**
- **Version:** 4.0.448
- **Used in:**
  - [`remotion-api/`](remotion-api/) — Node.js rendering service (Dockerized as `bob-remotion`)
  - [`docker-compose.yml`](docker-compose.yml) — `bob-remotion` service definition
  - Lab tooling that produces video output (e.g. [`templates/lab_examples/remotion_video_generator.lab.json`](templates/lab_examples/remotion_video_generator.lab.json), [`templates/lab_examples/video_editor.lab.json`](templates/lab_examples/video_editor.lab.json))

### Riffusion

Stable diffusion for real-time music generation.

- **Repository:** <https://github.com/riffusion/riffusion-hobby>
- **Website:** <https://riffusion.com/about>
- **Used in:** [`script-runner/scripts/riffusion.py`](script-runner/scripts/riffusion.py)

```bibtex
@article{Forsgren_Martiros_2022,
  author = {Forsgren, Seth* and Martiros, Hayk*},
  title = {{Riffusion - Stable diffusion for real-time music generation}},
  url = {https://riffusion.com/about},
  year = {2022}
}
```

---

## Lab blueprints — inspirations and adaptations

Several lab examples in [`templates/lab_examples/`](templates/lab_examples/)
are reproductions or open-source adaptations of public projects. Each lab keeps
the source attribution in its `description` field; this section centralizes
them. Bob Manager's adaptations are released under Apache 2.0; the original
authors retain credit for the underlying ideas and any quoted prompts.

| Lab | Source repository | Inspiration |
|---|---|---|
| [`loophole.lab.json`](templates/lab_examples/loophole.lab.json) | [brendanhogan/loophole](https://github.com/brendanhogan/loophole) | Adversarial moral-rule stress test: a legislator drafts policy, adversarial agents hunt loopholes and overreach, a judge resolves them. |
| [`3man.lab.json`](templates/lab_examples/3man.lab.json) | [russelleNVy/three-man-team](https://github.com/russelleNVy/three-man-team) | Three-agent software delivery: Architect plans, Builder implements, Reviewer gates. |
| [`auto_quant.lab.json`](templates/lab_examples/auto_quant.lab.json) | [TraderAlice/Auto-Quant](https://github.com/TraderAlice/Auto-Quant) | Quantitative trading research: hypothesis → data → strategy → backtest → risk audit → report. Research-grade only (no live execution). |
| [`vibe_trading.lab.json`](templates/lab_examples/vibe_trading.lab.json) | [HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) | Natural-language trading research: research → market context → strategy spec → backtest plan → risk → report. |
| [`video_editor.lab.json`](templates/lab_examples/video_editor.lab.json) | [poseljacob/agentic-video-editor](https://github.com/poseljacob/agentic-video-editor) | Multi-agent short-form video pipeline (the original is Gemini-based; Bob's adaptation uses LTX-Video / Wan-Video / MusicGen / Bark / Coqui / ffmpeg / Remotion). |

If you are the author of an upstream project listed above and want a different
attribution wording, the lab removed, or a license note added, open an issue
or PR.
