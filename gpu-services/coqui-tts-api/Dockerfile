FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv python3-dev build-essential \
    ffmpeg git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir uv && \
    uv pip install --system --no-cache 'numpy<2' && \
    uv pip install --system --no-cache torch torchaudio \
        --index-url https://download.pytorch.org/whl/cu121 && \
    uv pip install --system --no-cache -r requirements.txt \
        --extra-index-url https://download.pytorch.org/whl/cu121

COPY app.py .

# Speaker reference audio directory — mount .wav files here
VOLUME /speakers

# CSO #3 — drop root. /speakers is operator-mounted (typically read-
# only). HuggingFace cache for the Coqui model download lives under
# /app/.cache so the non-root user has write access. GPU device
# access is granted by the nvidia runtime regardless of in-container
# uid.
ENV HF_HOME=/app/.cache/huggingface
ENV XDG_CACHE_HOME=/app/.cache
RUN if ! id -u 1000 >/dev/null 2>&1; then \
        useradd -u 1000 -m -s /bin/bash gpu; \
    fi && mkdir -p /app/.cache && chown -R 1000:1000 /app
USER 1000

EXPOSE 3017

CMD ["python3", "app.py"]
