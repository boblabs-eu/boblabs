FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv ffmpeg git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir uv && \
    uv pip install --system --no-cache 'numpy<2' && \
    uv pip install --system --no-cache 'torch>=2.1.0,<2.6' torchaudio \
        --index-url https://download.pytorch.org/whl/cu121 && \
    uv pip install --system --no-cache -r requirements.txt \
        --extra-index-url https://download.pytorch.org/whl/cu121

COPY app.py .

# CSO #3 — drop root. Bark downloads its checkpoints from HuggingFace
# on first request via `bark.preload_models()`, which caches under
# ~/.cache/huggingface/. We point HF_HOME to /app/.cache so the
# non-root user has a writable cache location AND the operator's
# BARK_CHECKPOINT_DIR (the A10 manifest verifier) can find a stable
# path to validate against.
ENV HF_HOME=/app/.cache/huggingface
ENV XDG_CACHE_HOME=/app/.cache
RUN if ! id -u 1000 >/dev/null 2>&1; then \
        useradd -u 1000 -m -s /bin/bash gpu; \
    fi && mkdir -p /app/.cache && chown -R 1000:1000 /app
USER 1000

EXPOSE 3015

CMD ["python3", "app.py"]
