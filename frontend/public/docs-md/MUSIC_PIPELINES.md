# Bob Labs — Multi-Pipeline Song Generation

> **Implementation Status:**
> - ✅ MusicGen pipeline — **Implemented** (port 3014)
> - ✅ Bark pipeline — **Implemented** (port 3015)
> - ✅ RVC pipeline — **Implemented** (port 3016)
> - ✅ CoquiTTS / XTTS v2 pipeline — **Implemented** (port 3017)
> - ✅ STT (Speech-to-Text) — **Implemented** (port 7865)
> - ✅ `audio_mix` builtin tool — **Implemented**
> - ⏳ Demucs (source separation) — **Planned**
> - ⏳ DiffSinger (melodic singing) — **Planned**
> - ⏳ Matchering (auto-mastering) — **Planned**

## 1. Goal

Build a fully open-source, modular song generation system within bob-manager that can produce complete songs (instrumental + vocals + mix) comparable in structure to Suno/Udio, using chained GPU pipelines orchestrated by an LLM agent.

Each pipeline runs on GPU servers, is auto-discovered, and plugs into the existing `media_pipeline` tool. The LLM agent calls them sequentially, passing intermediate files between stages. The agent controls creative decisions (style, lyrics, structure) while pipelines handle the heavy inference.

---

## 2. Pipeline Chain Overview

```
                         LLM Agent (orchestrator)
                               │
            ┌──────────────────┼──────────────────────┐
            │                  │                       │
     ┌──────▼──────┐   ┌──────▼──────┐        ┌──────▼───────┐
     │  Stage 1    │   │  Stage 2    │        │  Stage 4     │
     │  MusicGen   │   │  Vocals     │        │  Mix/Master  │
     │  (instru-   │   │  (singing)  │        │  (FFmpeg +   │
     │   mental)   │   │             │        │   Pedalboard)│
     └──────┬──────┘   └──────┬──────┘        └──────▲───────┘
            │                 │                      │
            │          ┌──────▼──────┐               │
            │          │  Stage 3    │               │
            │          │  RVC        │               │
            │          │  (voice     │               │
            │          │   convert)  │               │
            │          └──────┬──────┘               │
            │                 │                      │
            └─────────────────┴──────────────────────┘
                    files passed via workspace
```

**The agent decides the order.** Typical flows:

| Flow | Steps | Best for |
|------|-------|----------|
| **A: Instrumental + TTS vocals** | MusicGen → CoquiTTS → RVC → Mix | Songs with clear lyrics |
| **B: Full gen then refine** | MusicGen (with vocals) → Demucs (separate) → RVC (re-voice) → Mix | Quick prototyping |
| **C: Riffusion loops + vocals** | Riffusion ×N → CoquiTTS → RVC → Mix | Short loops / lo-fi |
| **D: Instrumental only** | MusicGen → Mix/Master | BGM, soundtracks |

---

## 3. Pipeline Inventory — What To Use

### 3.1 Stage 1: Instrumental / Music Generation

#### MusicGen (Meta / AudioCraft) ★ IMPLEMENTED

| Property | Detail |
|----------|--------|
| **Repo** | https://github.com/facebookresearch/audiocraft |
| **License** | MIT (code), CC-BY-NC 4.0 (models) |
| **Models** | `musicgen-small` (300M), `musicgen-medium` (1.5B), `musicgen-large` (3.3B), `musicgen-melody` (1.5B+melody conditioning) |
| **Input** | Text prompt + optional melody audio (wav) for melody conditioning |
| **Output** | WAV audio (mono/stereo, configurable duration up to ~30s per chunk) |
| **VRAM** | small: ~4GB, medium: ~8GB, large: ~12GB, melody: ~8GB |
| **Quality** | Best open-source instrumental generation. Handles genres well. |
| **Key feature** | `musicgen-melody` can continue/extend from an existing audio clip — essential for generating songs longer than 30s by chaining chunks |

**Why MusicGen over others:**
- Stable Audio Open is good but models are less accessible for self-hosting
- MusicGen has the best ecosystem (audiocraft library, well-documented API)
- Melody conditioning allows chunk-chaining for longer tracks
- Active community, lots of fine-tunes available

**Serving:** Deploy as a FastAPI service using `audiocraft` Python library. Accept JSON with prompt + optional base64 audio input. Return base64 WAV.

#### Riffusion (already implemented)

Still useful for quick lo-fi loops and transitions. Complements MusicGen for different use cases.

---

### 3.2 Stage 2: Vocal / Singing Generation

Two sub-problems: (a) generating singing voice from lyrics, (b) generating spoken-word/rap.

#### Option A: CoquiTTS / XTTS v2 ★ IMPLEMENTED

| Property | Detail |
|----------|--------|
| **Repo** | https://github.com/idiap/coqui-ai-TTS (community fork, active) |
| **License** | MPL-2.0 |
| **Models** | XTTS v2 (multilingual, voice cloning from ~6s reference) |
| **Input** | Text + reference audio (speaker embedding) |
| **Output** | WAV audio |
| **VRAM** | ~4GB |
| **Quality** | Excellent for speech. Can approximate "talking over beat" / rap style. Not designed for singing melody. |

**Use for:** Narration, rap, spoken word, podcast-style vocals.

#### Option B: Bark (Suno) — for rough singing

| Property | Detail |
|----------|--------|
| **Repo** | https://github.com/suno-ai/bark |
| **License** | MIT |
| **Input** | Text with special tokens: `♪` for singing, `[laughs]`, `[sighs]`, etc. |
| **Output** | WAV audio (24kHz) |
| **VRAM** | ~6-8GB |
| **Quality** | Can produce singing but inconsistent pitch/melody. Good for rough drafts. |

**Use for:** Rough vocal demos that will be refined through RVC. The inconsistency is acceptable when RVC cleans it up.

#### Option C: DiffSinger — for melodic singing ★ FUTURE

| Property | Detail |
|----------|--------|
| **Repo** | https://github.com/openvpi/DiffSinger |
| **License** | Apache-2.0 |
| **Input** | MIDI + phoneme sequence (from lyrics) |
| **Output** | WAV audio |
| **VRAM** | ~4GB |
| **Quality** | High quality melodic singing when properly configured |
| **Complexity** | HIGH — requires MIDI alignment, phonemizer, voicebank training |

**Use for:** Future phase. Needs MIDI generation step (could add a MIDI pipeline or use MusicGen melody extraction). Best quality singing but most complex to deploy.

#### Recommended approach (pragmatic)

1. **Phase 1 (now):** Use **Bark** for rough singing → **RVC** to clean up
2. **Phase 2:** Add **CoquiTTS/XTTS** for speech/rap vocals
3. **Phase 3:** Add **DiffSinger** for high-quality melodic singing

---

### 3.3 Stage 3: Voice Conversion

#### RVC (Retrieval-based Voice Conversion) ★ IMPLEMENTED

| Property | Detail |
|----------|--------|
| **Repo** | https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI |
| **License** | MIT |
| **Input** | WAV audio + voice model (.pth) + optional index file |
| **Output** | WAV audio (converted voice) |
| **VRAM** | ~4GB |
| **Quality** | Excellent. Industry-standard for voice conversion. |
| **Key feature** | Can train custom voice models from ~10min of audio. Pre-trained models widely available. |

**Configuration per project:**
- Voice model (.pth file) stored as lab resource or on GPU server
- Parameters: pitch shift (semitones), filter radius, index ratio, protect ratio
- Agent selects voice model + pitch based on song style

**Serving:** Deploy the RVC inference core as a FastAPI service. Strip the Gradio WebUI, keep only the inference pipeline (`infer_pipeline.py`). Accept audio + model_name + params, return WAV.

#### Alternative: So-VITS-SVC

Similar quality to RVC but harder to set up. RVC is more actively maintained and has simpler inference. **Skip unless RVC doesn't meet needs.**

---

### 3.4 Stage 4: Mixing & Mastering

This stage does NOT need GPU. Two approaches:

#### Approach A: FFmpeg as a regular tool ★ IMPLEMENTED

| Operation | FFmpeg command |
|-----------|---------------|
| Mix two tracks | `ffmpeg -i vocals.wav -i instrumental.wav -filter_complex amix=inputs=2:duration=longest` |
| Volume adjust | `ffmpeg -i input.wav -af volume=0.8 output.wav` |
| EQ | `ffmpeg -i input.wav -af equalizer=f=1000:t=q:w=1:g=2 output.wav` |
| Compression | `ffmpeg -i input.wav -af acompressor=threshold=-20dB:ratio=4 output.wav` |
| Concat segments | `ffmpeg -i "concat:part1.wav\|part2.wav" -c copy output.wav` |
| Fade in/out | `ffmpeg -i input.wav -af afade=t=in:d=2,afade=t=out:st=28:d=2 output.wav` |
| Convert format | `ffmpeg -i input.wav -codec:a libmp3lame -qscale:a 2 output.mp3` |
| Normalize | `ffmpeg -i input.wav -af loudnorm=I=-14:TP=-1:LRA=11 output.wav` |

**This should be a regular builtin tool** (`audio_mix`), not a GPU pipeline. Runs on the control plane in a sandboxed container (like `python_exec`). FFmpeg is fast on CPU and doesn't need GPU.

#### Approach B: Pedalboard (Spotify) for advanced effects

| Property | Detail |
|----------|--------|
| **Repo** | https://github.com/spotify/pedalboard |
| **License** | GPL-3.0 |
| **Features** | Reverb, chorus, distortion, compressor, limiter, EQ, convolution, VST3/AU plugin hosting |

Can be used via `python_exec` with pedalboard pre-installed in the sandbox container. Gives the LLM access to professional audio effects: reverb, delay, chorus, compression, limiting, etc.

#### Approach C: Matchering for auto-mastering

| Property | Detail |
|----------|--------|
| **Repo** | https://github.com/sergree/matchering |
| **License** | GPL-3.0 |
| **Input** | Target audio + reference audio (a professionally mastered track) |
| **Output** | Mastered audio matching the reference's spectral profile |

Simple to use: give it your mix + a reference song → outputs a mastered track. Could be a Python function called via `python_exec`.

#### Recommended approach

1. **`audio_mix` builtin tool** — wraps FFmpeg for basic operations (mix, concat, fade, normalize, convert)
2. **Pedalboard via `python_exec`** — pre-install in sandbox container for advanced effects
3. **Matchering via `python_exec`** — auto-mastering with reference track

---

### 3.5 Bonus: Source Separation (Demucs)

#### Demucs (Meta)

| Property | Detail |
|----------|--------|
| **Repo** | https://github.com/adefossez/demucs |
| **License** | MIT |
| **Input** | Mixed audio (WAV/MP3) |
| **Output** | Separated stems: vocals, drums, bass, other |
| **VRAM** | ~4GB (benefits from GPU but can run on CPU) |

**Use case:** Extract stems from generated audio for re-mixing, or isolate vocals for RVC processing. Enables "generate full mix → separate → re-voice → re-mix" workflow.

**Priority:** Phase 2. Nice to have but not essential for initial song generation.

---

## 4. Architecture: How It Fits Into Bob Manager

### 4.1 What is a GPU Pipeline vs a Regular Tool

| Category | Runs on | Examples | Why |
|----------|---------|----------|-----|
| **GPU Pipeline** (`media_pipeline:*`) | GPU server, auto-discovered | MusicGen, Bark, RVC, CoquiTTS, Demucs, DiffSinger | Needs VRAM, model weights |
| **Builtin Tool** | Control plane, sandboxed | `audio_mix` (FFmpeg), `python_exec` (Pedalboard) | CPU-only, fast, no model |

### 4.2 GPU Pipeline Serving Pattern

Each GPU pipeline runs as a **standalone FastAPI service** on the GPU server, like riffusion today:

```
GPU Server (192.168.1.109)
├── riffusion-hobby   :3013   ← existing
├── musicgen-api      :3014   ← existing
├── bark-api          :3015   ← existing
├── rvc-api           :3016   ← existing
└── coqui-tts-api     :3017   ← existing
```

Each service:
- Has a `/health` endpoint for auto-discovery
- Has a `/generate` (or `/infer`) endpoint accepting JSON
- Returns base64-encoded output files
- Is registered as an `AIProvider` in bob-manager with `provider_type = "musicgen"` etc.

### 4.3 Pipeline ABC — Current vs Extended

The current `MediaPipeline` ABC handles text→media generation well. For chaining, we need pipelines that also accept **file inputs** (e.g., RVC takes audio in, not just text).

**Proposed extension to `PipelineResult`:**

```python
@dataclass
class PipelineResult:
    success: bool
    media_type: str = ""          # "audio", "image", "video"
    media_url: str = ""           # base64 data URL (primary output)
    preview_url: str = ""         # preview/thumbnail
    duration_s: float = 0.0
    params_used: dict = field(default_factory=dict)
    error: str = ""
    raw: dict = field(default_factory=dict)
    # NEW: support multiple named outputs (e.g., demucs stems)
    extra_outputs: dict[str, str] = field(default_factory=dict)
    #   e.g. {"vocals": "base64...", "drums": "base64...", "bass": "base64..."}
```

**Proposed extension to `build_tool_params` contract:**

Pipelines that accept file inputs declare an `input_file` parameter in their tool schema. The `_media_pipeline` handler reads the workspace file, base64-encodes it, and passes it in the `extra` dict as `input_audio_b64`. The pipeline's `build_tool_params()` handles the rest.

```
LLM calls: media_pipeline(pipeline="rvc", prompt="convert to female voice",
                           params={"input_file": "output/generated_audio/bark_1712345678.wav",
                                   "model_name": "female_pop_v2", "pitch_shift": 4})
    ↓
_media_pipeline handler reads the file from workspace, adds input_audio_b64
    ↓
RVCPipeline.build_tool_params(prompt, {input_audio_b64: "...", model_name: "...", ...})
    ↓
POST to rvc-api /infer with audio + model + params
    ↓
Returns converted audio
```

This keeps the `MediaPipeline` ABC unchanged — the `extra` dict is flexible enough.

### 4.4 The `audio_mix` Builtin Tool

A new tool in `BUILTIN_TOOLS` (not a GPU pipeline):

```python
"audio_mix": {
    "name": "audio_mix",
    "description": "Mix, concatenate, normalize, and process audio files using FFmpeg.",
    "parameters": {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["mix", "concat", "volume", "fade", "normalize", "convert", "trim", "eq"],
                "description": "The audio operation to perform"
            },
            "input_files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Workspace-relative paths to input audio files"
            },
            "output_file": {
                "type": "string",
                "description": "Workspace-relative path for the output file"
            },
            "params": {
                "type": "object",
                "description": "Operation-specific parameters (volume level, fade duration, etc.)"
            }
        },
        "required": ["operation", "input_files", "output_file"]
    }
}
```

Executes FFmpeg commands inside the sandboxed container. Validates all file paths are within workspace. No GPU needed.

### 4.5 File Flow Between Pipelines

Files are the communication channel between pipeline stages. The LLM agent manages the flow:

```
Agent Iteration 1:
  → media_pipeline(pipeline="musicgen", prompt="upbeat pop instrumental, C major, 120 BPM, verse section")
  ← output/generated_audio/musicgen_1712345001.wav

Agent Iteration 2:
  → media_pipeline(pipeline="musicgen", prompt="upbeat pop instrumental, chorus, more energy",
                   params={"continuation_audio": "output/generated_audio/musicgen_1712345001.wav"})
  ← output/generated_audio/musicgen_1712345002.wav

Agent Iteration 3:
  → audio_mix(operation="concat",
              input_files=["output/generated_audio/musicgen_1712345001.wav",
                           "output/generated_audio/musicgen_1712345002.wav"],
              output_file="output/song/instrumental.wav")
  ← output/song/instrumental.wav

Agent Iteration 4:
  → media_pipeline(pipeline="bark", prompt="♪ You light up my world, every single day ♪")
  ← output/generated_audio/bark_1712345003.wav

Agent Iteration 5:
  → media_pipeline(pipeline="rvc",
                   prompt="convert to target voice",
                   params={"input_file": "output/generated_audio/bark_1712345003.wav",
                           "model_name": "female_pop_v2", "pitch_shift": 2})
  ← output/generated_audio/rvc_1712345004.wav

Agent Iteration 6:
  → audio_mix(operation="mix",
              input_files=["output/song/instrumental.wav",
                           "output/generated_audio/rvc_1712345004.wav"],
              output_file="output/song/final_mix.wav",
              params={"volumes": [0.7, 1.0]})
  ← output/song/final_mix.wav

Agent Iteration 7:
  → audio_mix(operation="normalize", input_files=["output/song/final_mix.wav"],
              output_file="output/song/final_master.mp3",
              params={"target_lufs": -14, "format": "mp3"})
  ← output/song/final_master.mp3
```

---

## 5. Implementation Plan

### Phase 1: MusicGen Pipeline + audio_mix Tool

**Priority: HIGH — enables instrumental generation + basic mixing**

| Task | Effort | Notes |
|------|--------|-------|
| Deploy MusicGen FastAPI service on GPU server | 1 day | audiocraft + FastAPI wrapper, port 3014 |
| Write `MusicGenPipeline` class | 0.5 day | Extends `MediaPipeline`, supports text + melody conditioning + continuation |
| Register in `PIPELINE_REGISTRY` | 5 min | Add to `__init__.py` |
| Add `audio_mix` builtin tool | 0.5 day | FFmpeg wrapper in `tool_executor.py`, sandboxed |
| Extend `_media_pipeline` handler for file inputs | 0.5 day | Read workspace file → base64 → pass to pipeline |
| Test full flow: generate + concat + normalize | 0.5 day | End-to-end song structure |

**MusicGen API service spec:**

```
POST /generate
{
  "prompt": "upbeat electronic pop, C major, 120bpm",
  "duration": 30.0,           // seconds, max 30
  "model": "medium",          // small|medium|large|melody
  "temperature": 1.0,
  "top_k": 250,
  "top_p": 0.0,
  "continuation_audio": "base64...",  // optional: continue from this audio
  "melody_audio": "base64...",        // optional: melody conditioning (melody model only)
  "sample_rate": 32000
}

Response:
{
  "audio": "base64...",       // WAV
  "duration_s": 30.0,
  "sample_rate": 32000
}
```

### Phase 2: Bark + RVC (Vocal Pipeline)

**Priority: HIGH — enables full songs with vocals**

| Task | Effort | Notes |
|------|--------|-------|
| Deploy Bark FastAPI service on GPU server | 0.5 day | Simple wrapper, port 3015 |
| Write `BarkPipeline` class | 0.5 day | Text → audio with `♪` singing tokens |
| Deploy RVC inference FastAPI service | 1 day | Strip WebUI, keep inference core, port 3016 |
| Write `RVCPipeline` class | 0.5 day | Takes audio input + voice model name |
| Prepare 2-3 starter voice models | 0.5 day | Train on royalty-free voice samples |
| Test full vocal chain: Bark → RVC → mix | 0.5 day | |

**Bark API service spec:**

```
POST /generate
{
  "prompt": "♪ Hello world, this is a test song ♪",
  "speaker": "v2/en_speaker_6",    // optional bark speaker preset
  "temperature": 0.7,
  "sample_rate": 24000
}

Response:
{
  "audio": "base64...",
  "duration_s": 5.2,
  "sample_rate": 24000
}
```

**RVC API service spec:**

```
POST /infer
{
  "audio": "base64...",            // input WAV
  "model_name": "female_pop_v2",   // model .pth on server
  "pitch_shift": 0,                // semitones (-12 to +12)
  "filter_radius": 3,
  "index_ratio": 0.75,
  "rms_mix_rate": 0.25,
  "protect": 0.33,
  "f0_method": "rmvpe"             // rmvpe|crepe|harvest|pm
}

Response:
{
  "audio": "base64...",
  "duration_s": 5.2,
  "sample_rate": 40000
}
```

### Phase 3: CoquiTTS + Demucs (Extended Capabilities)

**Priority: MEDIUM**

| Task | Effort | Notes |
|------|--------|-------|
| Deploy XTTS v2 FastAPI service | 0.5 day | Voice cloning TTS, port 3017 |
| Write `CoquiTTSPipeline` class | 0.5 day | Text + reference voice → speech |
| Deploy Demucs FastAPI service | 0.5 day | Source separation, port 3018 |
| Write `DemucsPipeline` class | 0.5 day | Audio in → stems out (uses `extra_outputs`) |
| Add `extra_outputs` handling to `_media_pipeline` | 0.5 day | Save multiple output files |

### Phase 4: DiffSinger + Advanced (Future)

**Priority: LOW — high complexity, nice-to-have**

| Task | Effort | Notes |
|------|--------|-------|
| MIDI generation pipeline (MusicGen melody → MIDI extraction) | Research | Complex |
| DiffSinger service + voicebank training | 2-3 days | Highest quality singing |
| Pedalboard effects in sandbox container | 0.5 day | Pre-install in python_exec image |
| Matchering auto-mastering | 0.5 day | python_exec or dedicated tool |

---

## 6. VRAM Budget

On a single GPU server (e.g., RTX 3090 24GB):

| Service | VRAM at rest | VRAM during inference | Can coexist? |
|---------|-------------|----------------------|--------------|
| Riffusion | ~3GB | ~5GB | Yes |
| MusicGen-medium | ~0GB (load on demand) | ~8GB | Yes, if sequential |
| Bark | ~0GB (load on demand) | ~6GB | Yes, if sequential |
| RVC | ~0GB (load on demand) | ~4GB | Yes |
| CoquiTTS | ~0GB (load on demand) | ~4GB | Yes |
| Demucs | ~0GB (load on demand) | ~4GB | Yes |

**Strategy:** Load models on demand, unload after inference (or after timeout). Only one heavy model active at a time. The LLM agent calls them sequentially anyway.

For multiple GPU servers, different services can be distributed:
```
GPU Server A (24GB): riffusion + musicgen + bark
GPU Server B (24GB): rvc + coqui-tts + demucs
```

Each service registers as a separate `AIProvider` with its own `base_url` pointing to the correct server.

---

## 7. What Stays Open Source

| Component | License | Commercial OK? |
|-----------|---------|----------------|
| MusicGen code (audiocraft) | MIT | ✅ Yes |
| MusicGen models | CC-BY-NC 4.0 | ❌ Non-commercial only* |
| Bark | MIT | ✅ Yes |
| RVC | MIT | ✅ Yes |
| CoquiTTS / XTTS v2 | MPL-2.0 | ✅ Yes |
| Demucs | MIT | ✅ Yes |
| DiffSinger | Apache-2.0 | ✅ Yes |
| FFmpeg | LGPL-2.1 / GPL-2.0 | ✅ Yes (LGPL build) |
| Pedalboard | GPL-3.0 | ⚠️ Copyleft |
| Matchering | GPL-3.0 | ⚠️ Copyleft |

*MusicGen model weights are CC-BY-NC. For commercial use, alternatives exist (fine-tune your own, or use fully open models when available). For personal/research use: no issue.

**Verdict: Yes, fully open-source is achievable.** All code is MIT/Apache/MPL. Model weights are the only restriction (MusicGen NC). Bark, RVC, CoquiTTS, Demucs are all permissively licensed.

---

## 8. Minimal Code Changes Required

### Already done (from media_pipeline implementation):
- ✅ `MediaPipeline` ABC with `build_tool_params()`, `tool_description()`, `generate()`, `validate_params()`
- ✅ `PIPELINE_REGISTRY` with dynamic registration
- ✅ `_media_pipeline` generic handler in `tool_executor.py`
- ✅ Pipeline sub-selection UI (`media_pipeline:riffusion`, etc.)
- ✅ `GET /orchestrator/pipelines` API endpoint

### Still needed:

#### 8.1 Extend `_media_pipeline` handler for file inputs

In `tool_executor.py`, before calling `pipeline.build_tool_params()`, check for `input_file` in params:

```python
# If pipeline params reference a workspace file, read and base64-encode it
input_file = extra.get("input_file")
if input_file:
    file_path = self.workspace / input_file
    if not file_path.is_file():
        return {"success": False, "output": f"Input file not found: {input_file}"}
    import base64
    extra["input_audio_b64"] = base64.b64encode(file_path.read_bytes()).decode()
```

#### 8.2 Extend `PipelineResult` for multi-file output

Add `extra_outputs: dict[str, str]` field for pipelines that produce multiple files (Demucs stems).

#### 8.3 New pipeline classes

One file per pipeline in `control-plane/app/services/pipelines/`:
- `musicgen.py` — `MusicGenPipeline`
- `bark.py` — `BarkPipeline`
- `rvc.py` — `RVCPipeline`
- `coqui_tts.py` — `CoquiTTSPipeline` (Phase 3)
- `demucs.py` — `DemucsPipeline` (Phase 3)

Register each in `__init__.py` → `PIPELINE_REGISTRY`.

#### 8.4 New `audio_mix` builtin tool

New entry in `BUILTIN_TOOLS`, new handler `_audio_mix()` in `tool_executor.py`.
Add to `BUILTIN_TOOL_LIST` in `LabsView.js`.

#### 8.5 GPU server FastAPI services

Standalone services in a new `gpu-services/` directory:
```
gpu-services/
├── musicgen-api/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app.py
├── bark-api/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app.py
├── rvc-api/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app.py
└── install.sh       # systemd installer for all services
```

---

## 9. Summary — Recommended Priority Order

| # | What | Pipelines | Result |
|---|------|-----------|--------|
| **1** | MusicGen + audio_mix | `musicgen`, `audio_mix` | Full instrumentals, multi-section songs, mixing |
| **2** | Bark + RVC | `bark`, `rvc` | Vocals: rough singing → realistic voice |
| **3** | CoquiTTS | `coqui_tts` | High-quality speech/rap vocals |
| **4** | Demucs | `demucs` | Stem separation for advanced workflows |
| **5** | DiffSinger | `diffsinger` | High-quality melodic singing (complex) |

After Phase 1+2, the system can produce complete songs: instrumental + vocals + mix. Phase 3+ adds refinement and flexibility.
