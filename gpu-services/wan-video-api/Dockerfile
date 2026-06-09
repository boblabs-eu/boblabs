FROM nvidia/cuda:12.8.1-devel-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-dev python3-venv \
        git ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

# Install PyTorch (CUDA 12.8) + core deps
RUN pip3 install --break-system-packages --no-cache-dir \
        torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128

# Install diffusers from main branch (Wan 2.2 support)
RUN pip3 install --break-system-packages --no-cache-dir \
        "git+https://github.com/huggingface/diffusers"

# Wan 2.2 dependencies
RUN pip3 install --break-system-packages --no-cache-dir \
        transformers accelerate sentencepiece protobuf \
        ftfy imageio imageio-ffmpeg

# API dependencies
RUN pip3 install --break-system-packages --no-cache-dir \
        fastapi 'uvicorn[standard]' pydantic 'python-multipart>=0.0.6' pillow

WORKDIR /app
COPY app.py .

EXPOSE 3019

ENV PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility
ENV WAN_HOST=0.0.0.0
ENV WAN_PORT=3019

# CSO #3 — drop root. Wan-2.2 weights pulled from HuggingFace on
# first request; cache under /app/.cache.
ENV HF_HOME=/app/.cache/huggingface
ENV XDG_CACHE_HOME=/app/.cache
RUN if ! id -u 1000 >/dev/null 2>&1; then \
        useradd -u 1000 -m -s /bin/bash gpu; \
    fi && mkdir -p /app/.cache && chown -R 1000:1000 /app
USER 1000

CMD ["python3", "app.py"]
