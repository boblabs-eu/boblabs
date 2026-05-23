# Bob Labs — YouTube Speech Retrieval — Tool Design

> **Status: ✅ Partially Implemented** — The `youtube` builtin tool (audio download via yt-dlp) and STT GPU service (port 7865) are implemented. The full pipeline (download → transcribe → summarize → RAG ingest) can be orchestrated by a Lab agent using these tools. This document captures the original design.

> ~~Planning document for a YouTube audio extraction and speech-to-text tool in Bob Manager.~~
> ~~Follows the existing "specialized model as tool" pattern (same as media pipelines).~~

---

## Table of Contents

1. [Overview](#1-overview)
2. [Pipeline Architecture](#2-pipeline-architecture)
3. [Step 1: Audio Download (yt-dlp)](#3-step-1-audio-download-yt-dlp)
4. [Step 2: Speech-to-Text (STT Model)](#4-step-2-speech-to-text-stt-model)
5. [Step 3: Store and Summarize](#5-step-3-store-and-summarize)
6. [Step 4: RAG Ingestion (Optional)](#6-step-4-rag-ingestion-optional)
7. [STT Model Comparison](#7-stt-model-comparison)
8. [Chunking Strategy for Long Audio](#8-chunking-strategy-for-long-audio)
9. [Tool Design](#9-tool-design)
10. [GPU Service Design](#10-gpu-service-design)
11. [API Endpoints](#11-api-endpoints)
12. [Implementation Plan](#12-implementation-plan)
13. [Future: Real Pipeline Chaining](#13-future-real-pipeline-chaining)

---

## 1. Overview

Extract speech from YouTube videos and convert to text for analysis, summarization, and RAG ingestion.

```
YouTube URL → Download Audio → STT Model → Full Transcript → File
                                                            → Summary (via LLM)
                                                            → RAG Collection (optional)
```

### Use Cases

- Transcribe conference talks, lectures, podcasts
- Build knowledge bases from video content
- Summarize long-form video content for research
- Index video libraries for semantic search via RAG

---

## 2. Pipeline Architecture

Following the existing pattern from `music_pipelines.md` — each stage is a **standalone tool** or **GPU service**, not a hardcoded pipeline. The LLM agent orchestrates the flow.

```
┌─────────────────────────────────────────────────────────────┐
│  Agent Workflow (orchestrated by LLM)                       │
│                                                             │
│  1. youtube_audio_download(url)                             │
│     → /workspace/output/audio.mp3                           │
│                                                             │
│  2. speech_to_text(audio_path)                              │
│     → { text, segments[], language, duration }              │
│     → saves /workspace/output/transcript.txt                │
│                                                             │
│  3. LLM reads transcript → generates summary               │
│     → saves /workspace/output/summary.md                    │
│                                                             │
│  4. (optional) rag_ingest from transcript file              │
│     → chunks go into RAG collection                         │
└─────────────────────────────────────────────────────────────┘
```

**Why tools, not a hardcoded pipeline**: Same reasoning as music pipelines — the agent decides the flow, can skip or repeat steps, handle errors, and adapt. For example, if the video already has a subtitle track, the agent could skip STT entirely. This keeps the implementation simple and consistent with existing architecture.

---

## 3. Step 1: Audio Download (yt-dlp)

### Tool: `youtube_audio_download`

**Runs on**: Control plane (CPU, lightweight)

```python
# Dependencies: yt-dlp (pip install yt-dlp)
# Optional: ffmpeg for format conversion

import subprocess
import os

def download_audio(url: str, output_dir: str, format: str = "mp3") -> dict:
    """Download audio from a YouTube URL."""
    output_path = os.path.join(output_dir, f"audio.%(ext)s")
    cmd = [
        "yt-dlp",
        "-f", "bestaudio",
        "--extract-audio",
        "--audio-format", format,
        "--audio-quality", "0",      # best quality
        "--no-playlist",             # single video only
        "--max-filesize", "500M",    # safety limit
        "-o", output_path,
        url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    # Return path to downloaded file
    ...
```

### Security Considerations

- **URL validation**: Only allow `youtube.com` and `youtu.be` domains (prevent SSRF)
- **No playlist support**: `--no-playlist` prevents downloading entire channels
- **File size limit**: `--max-filesize 500M` prevents disk exhaustion  
- **Timeout**: 5-minute download timeout
- **Sandbox execution**: Runs inside the lab container, no host access

### Output

```json
{
  "success": true,
  "output_path": "/workspace/output/audio.mp3",
  "title": "Video Title",
  "duration_seconds": 3600,
  "filesize_bytes": 52428800
}
```

---

## 4. Step 2: Speech-to-Text (STT Model)

### Tool: `speech_to_text`

**Runs on**: GPU service (dedicated STT container) — same pattern as MusicGen, Bark, etc.

The STT tool calls a GPU service endpoint that runs the model. The control plane proxies the request.

### GPU Service: `stt-api`

A FastAPI service similar to `musicgen-api` or `bark-api`:

```python
# gpu-services/stt-api/app.py
from fastapi import FastAPI, UploadFile
import whisper  # or faster-whisper

app = FastAPI()
model = None

@app.on_event("startup")
async def load_model():
    global model
    model = whisper.load_model("large-v3")  # or faster-whisper

@app.get("/health")
async def health():
    return {"status": "ok", "model": "whisper-large-v3"}

@app.post("/transcribe")
async def transcribe(
    file: UploadFile,
    language: str = None,       # auto-detect if None
    task: str = "transcribe",   # "transcribe" or "translate" (to English)
    chunk_length: int = 30,     # seconds per chunk for Whisper
):
    # Save uploaded file, run model, return result
    result = model.transcribe(audio_path, language=language, task=task)
    return {
        "text": result["text"],
        "segments": result["segments"],  # [{start, end, text}, ...]
        "language": result["language"],
        "duration": result.get("duration", 0),
    }
```

### Docker Compose

```yaml
# gpu-services/docker-compose.yml (or docker-compose.stt.yml)
services:
  stt-api:
    build: ./stt-api
    ports:
      - "7865:7865"
    volumes:
      - stt_models:/root/.cache
    deploy:
      resources:
        reservations:
          devices:
            - capabilities: [gpu]
    environment:
      - MODEL_SIZE=large-v3
```

---

## 5. Step 3: Store and Summarize

After STT produces the transcript:

1. **Store full transcript**: The agent writes it to a file using `file_write` (existing tool)
2. **Generate summary**: The agent (LLM) reads the transcript and produces a summary — this is native LLM behavior, no special tool needed
3. **Save summary**: Written to file via `file_write`

This step requires **no new tooling** — the LLM orchestrator handles it naturally.

---

## 6. Step 4: RAG Ingestion (Optional)

If the user wants the transcript searchable, the agent can ingest it:

### Option A: Manual Upload (current)
User downloads the transcript file and uploads it to a RAG collection via the UI.

### Option B: Agent-Triggered Ingestion (new tool)

Add a `rag_ingest` tool that lets agents push content into collections they have **write access** to:

```python
BUILTIN_TOOLS["rag_ingest"] = {
    "description": "Ingest text content into a RAG collection this lab has write access to.",
    "parameters": {
        "collection": {"type": "string", "description": "Collection name", "required": True},
        "content": {"type": "string", "description": "Text content to ingest"},
        "source_file": {"type": "string", "description": "Path to workspace file to ingest (alternative to content)"},
        "filename": {"type": "string", "description": "Source label for the ingested document"},
        "metadata": {"type": "object", "description": "Optional metadata tags"},
    },
}
```

This is where the **`can_write` permission** in `lab_rag_access` becomes meaningful — only labs with write access can ingest.

---

## 7. STT Model Comparison

| Model | Size | VRAM | Speed (1hr audio) | Quality | Language Support | License |
|-------|------|------|--------------------|---------|------------------|---------|
| **Whisper large-v3** | 1.5GB | ~4GB | ~10 min (GPU) | Excellent | 100+ languages | MIT |
| **Whisper medium** | 769MB | ~3GB | ~6 min (GPU) | Very good | 100+ languages | MIT |
| **Whisper base** | 74MB | ~1GB | ~2 min (GPU) | Good | 100+ languages | MIT |
| **faster-whisper large-v3** | 1.5GB | ~4GB | ~3 min (GPU) | Excellent | 100+ languages | MIT |
| **Voxtral (Mistral)** | ~8GB | ~16GB | ~5 min (GPU) | Excellent | 30+ languages | Apache 2.0 |
| **Whisper.cpp** | 1.5GB | CPU | ~20 min (CPU) | Excellent | 100+ languages | MIT |

### Recommendation

**faster-whisper** (CTranslate2 backend for Whisper):
- **4x faster** than standard Whisper with same quality
- Same model weights, just optimized inference
- Lower VRAM usage via int8 quantization
- Best speed/quality/resource tradeoff

**Voxtral** is excellent but needs significantly more VRAM (16GB). Good second option for users with larger GPUs. Could be added as a second STT pipeline (same pattern as having both MusicGen and Riffusion).

---

## 8. Chunking Strategy for Long Audio

### Whisper's Internal Chunking

Whisper processes audio in **30-second chunks** internally. A 2-hour video is processed as ~240 segments automatically. No manual chunking needed for Whisper — it handles this natively.

**Maximum input**: No hard limit. Whisper processes any length audio by sliding 30s windows. A 6-hour podcast works fine.

### For RAG Ingestion

The transcript text should be chunked for RAG, **not the audio**:

```
Audio (2h) → Whisper → Full transcript (50,000 words)
                            ↓
                    RAG chunking (text level):
                    - Paragraph splitter (natural breaks)
                    - Or timestamp-based: group Whisper segments 
                      into 2-5 minute blocks
```

**Timestamp-aware chunking** is valuable for video transcripts — each chunk retains its timestamp range, letting agents cite "at 14:30 in the video" in their responses.

```python
def chunk_by_timestamp(segments, target_duration_sec=180):
    """Group Whisper segments into ~3-minute chunks with timestamps."""
    chunks = []
    current_chunk = {"start": 0, "end": 0, "text": ""}
    for seg in segments:
        current_chunk["text"] += " " + seg["text"]
        current_chunk["end"] = seg["end"]
        if seg["end"] - current_chunk["start"] >= target_duration_sec:
            chunks.append(current_chunk)
            current_chunk = {"start": seg["end"], "end": seg["end"], "text": ""}
    if current_chunk["text"].strip():
        chunks.append(current_chunk)
    return chunks
```

Each chunk's metadata would include `{"start_time": 840.0, "end_time": 1020.0}`, making it filterable in RAG search.

---

## 9. Tool Design

### Following Existing Pattern

Like `media_pipeline:riffusion`, we register STT as a pipeline tool:

```python
# control-plane/app/services/pipelines/stt.py
class STTPipeline(MediaPipeline):
    """Speech-to-text pipeline using Whisper/faster-whisper."""
    
    name = "stt"
    media_type = "text"
    
    def tool_description(self):
        return "Transcribe audio to text using speech-to-text model."
    
    def build_tool_params(self, prompt, extra):
        return {
            "audio_path": extra.get("audio_path"),
            "language": extra.get("language"),
            "task": extra.get("task", "transcribe"),
        }
    
    async def generate(self, params):
        # POST to stt-api service /transcribe endpoint
        ...
```

### Tool: `youtube_audio_download`

This is a **builtin tool** (CPU, no GPU service needed), similar to `web_extract`:

```python
BUILTIN_TOOLS["youtube_audio_download"] = {
    "description": "Download audio from a YouTube video URL. Returns the path to the audio file.",
    "parameters": {
        "url": {"type": "string", "description": "YouTube video URL", "required": True},
        "format": {"type": "string", "description": "Audio format: mp3, wav, m4a (default: mp3)"},
    },
}
```

### Tool: `rag_ingest` (new)

```python
BUILTIN_TOOLS["rag_ingest"] = {
    "description": "Ingest a text file or content into a RAG collection this lab has write access to.",
    "parameters": {
        "collection": {"type": "string", "description": "Collection name", "required": True},
        "source_file": {"type": "string", "description": "Path to file in workspace to ingest"},
        "content": {"type": "string", "description": "Raw text content to ingest (if no file)"},
        "filename": {"type": "string", "description": "Label for the document source", "required": True},
        "metadata": {"type": "object", "description": "Optional metadata tags (e.g. {\"source\": \"youtube\", \"video_id\": \"...\"})" },
    },
}
```

---

## 10. GPU Service Design

### Directory Structure

```
gpu-services/
  stt-api/
    app.py            # FastAPI with /health and /transcribe
    Dockerfile        # Python + faster-whisper + ffmpeg
    requirements.txt  # faster-whisper, fastapi, uvicorn, python-multipart
```

### Dockerfile

```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7865"]
```

### Requirements

```
faster-whisper>=1.0.0
fastapi>=0.100.0
uvicorn>=0.23.0
python-multipart>=0.0.6
```

### Registration

Register as an `AIProvider` with `provider_type = "stt"`, same as other GPU services. Auto-discovered via health check.

---

## 11. API Endpoints

### STT Service (GPU)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check + model info |
| `POST` | `/transcribe` | Transcribe audio file → text |

### Control Plane (new routes, optional for direct API access)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/tools/youtube-download` | Download YouTube audio (admin/debug) |
| `POST` | `/api/v1/tools/transcribe` | Transcribe audio file (admin/debug) |

These admin endpoints are optional — agents use the tool system, not direct API calls.

---

## 12. Implementation Plan

### Phase 1: STT GPU Service

| # | Task | File |
|---|------|------|
| 1 | Create stt-api FastAPI service | `gpu-services/stt-api/app.py` |
| 2 | Dockerfile with faster-whisper + ffmpeg | `gpu-services/stt-api/Dockerfile` |
| 3 | Requirements file | `gpu-services/stt-api/requirements.txt` |
| 4 | Docker compose for STT service | `docker-compose.stt.yml` |
| 5 | Register STT as pipeline in registry | `control-plane/app/services/pipelines/stt.py` |
| 6 | Register in PIPELINE_REGISTRY | `control-plane/app/services/pipelines/__init__.py` |

### Phase 2: YouTube Download Tool

| # | Task | File |
|---|------|------|
| 7 | Add yt-dlp to sandbox/requirements.txt | `sandbox/requirements.txt` |
| 8 | Add youtube_audio_download builtin tool | `control-plane/app/services/tool_executor.py` |
| 9 | URL validation (YouTube domains only) | `control-plane/app/services/tool_executor.py` |
| 10 | Add ffmpeg to sandbox Dockerfile | `sandbox/Dockerfile` |

### Phase 3: RAG Ingest Tool

| # | Task | File |
|---|------|------|
| 11 | Add rag_ingest builtin tool definition | `control-plane/app/services/tool_executor.py` |
| 12 | Implement _rag_ingest handler (checks can_write) | `control-plane/app/services/tool_executor.py` |
| 13 | Update augment_tool_names_with_rag_access for rag_ingest | `control-plane/app/services/lab_runner.py` |

### Phase 4: End-to-End Testing

| # | Task |
|---|------|
| 14 | Test: Download YouTube audio → transcribe → save file |
| 15 | Test: Transcript → RAG ingest → search |
| 16 | Test: Full agent workflow (LLM orchestrates all steps) |

---

## 13. Future: Real Pipeline Chaining

Current state: "Pipelines" are individual tools. The LLM agent calls them one by one. This works but:
- Agent may call tools in wrong order
- Agent may skip steps or hallucinate intermediate results
- No guaranteed execution flow

**Future improvement**: Define **pipeline chains** as ordered sequences:

```yaml
youtube_speech_pipeline:
  steps:
    - tool: youtube_audio_download
      input: { url: "$input.url" }
      output: audio_path
    - tool: speech_to_text  
      input: { audio_path: "$steps[0].audio_path" }
      output: transcript
    - tool: file_write
      input: { path: "transcript.txt", content: "$steps[1].transcript.text" }
    - tool: rag_ingest
      input: { collection: "$input.collection", source_file: "transcript.txt" }
      condition: "$input.collection != null"
```

This would be a **pipeline runner** that enforces step order and passes outputs between steps automatically. The agent calls `youtube_speech_pipeline(url, collection?)` as a single tool.

**For now**: Keep using individual tools orchestrated by the LLM. This is simpler, already works with the existing tool system, and gives the agent flexibility. We'll add pipeline chaining later when we have more complex multi-step workflows.
