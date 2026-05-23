# Bob Labs — Video Generation

## Overview

Bob Labs supports video generation through three complementary systems:

1. **LTX-Video** — AI text/image-to-video generation (GPU pipeline)
2. **Wan-Video** — AI text/image-to-video generation (GPU pipeline)
3. **Remotion** — Programmatic React-to-MP4 video rendering

## AI Video Generation

### LTX-Video (Port 3018)

GPU-accelerated text-to-video and image-to-video generation.

| Property | Detail |
|----------|--------|
| **Port** | 3018 |
| **VRAM** | ~12 GB |
| **Input** | Text prompt + optional reference image |
| **Output** | MP4 video |

**API:**
```json
POST /generate
{
  "prompt": "A cat walking through a garden, cinematic lighting",
  "num_frames": 48,
  "width": 768,
  "height": 512
}
```

See [INSTALL_LTX_VIDEO.md](INSTALL_LTX_VIDEO.md) for installation guide.

### Wan-Video (Port 3019)

Alternative AI video generation model with different strengths.

| Property | Detail |
|----------|--------|
| **Port** | 3019 |
| **VRAM** | ~14 GB |
| **Input** | Text prompt + optional reference image |
| **Output** | MP4 video |

See [INSTALL_WAN_VIDEO.md](INSTALL_WAN_VIDEO.md) for installation guide.

### Integration with Labs

Both video services are accessible through the `video_generate` builtin tool:

```json
{
  "name": "video_generate",
  "arguments": {
    "prompt": "A sunrise over mountains, time-lapse style",
    "pipeline": "ltx_video"
  }
}
```

The tool dispatches to the appropriate GPU service via the agent's configured URL (`LTX_VIDEO_URL` or `WAN_VIDEO_URL`).

## Remotion — Programmatic Video

Remotion enables React-based programmatic video rendering. The `bob-remotion` service runs as part of the control plane docker-compose stack.

### Architecture

```
Lab Agent → video_generate tool → bob-remotion API → Chromium render → MP4
```

### Service

| Property | Detail |
|----------|--------|
| **Container** | `bob-remotion` |
| **Port** | 3100 |
| **Source** | `remotion-api/server.mjs` |
| **Rendering** | Headless Chromium via Remotion |

### Demo Video Project

The `demo-video/` directory contains a Remotion project for generating platform demo videos:

```
demo-video/
├── package.json
├── remotion.config.ts
├── tsconfig.json
└── src/
    └── (React composition files)
```

## Related Documents

- [GPU_SERVICES.md](GPU_SERVICES.md) — All GPU services
- [INSTALL_LTX_VIDEO.md](INSTALL_LTX_VIDEO.md) — LTX-Video installation
- [INSTALL_WAN_VIDEO.md](INSTALL_WAN_VIDEO.md) — Wan-Video installation
- [TOOLS_AND_SANDBOX.md](TOOLS_AND_SANDBOX.md) — Tool reference
