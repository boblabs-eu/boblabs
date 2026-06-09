FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv ffmpeg git \
    build-essential python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir uv && \
    uv pip install --system --no-cache 'numpy<2' && \
    uv pip install --system --no-cache torch torchaudio \
        --index-url https://download.pytorch.org/whl/cu121 && \
    uv pip install --system --no-cache -r requirements.txt \
        --extra-index-url https://download.pytorch.org/whl/cu121

# Clone RVC inference modules (model definitions + VC pipeline)
RUN git clone --depth 1 --filter=blob:none --sparse \
        https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI.git /tmp/rvc && \
    cd /tmp/rvc && \
    git sparse-checkout set infer/lib/infer_pack infer/modules/vc && \
    mkdir -p /app/infer/lib/infer_pack /app/infer/modules/vc && \
    cp -r /tmp/rvc/infer/__init__.py /app/infer/ 2>/dev/null; \
    cp -r /tmp/rvc/infer/lib/__init__.py /app/infer/lib/ 2>/dev/null; \
    cp -r /tmp/rvc/infer/lib/infer_pack/* /app/infer/lib/infer_pack/ && \
    cp -r /tmp/rvc/infer/modules/__init__.py /app/infer/modules/ 2>/dev/null; \
    cp -r /tmp/rvc/infer/modules/vc/* /app/infer/modules/vc/ && \
    touch /app/infer/__init__.py /app/infer/lib/__init__.py /app/infer/modules/__init__.py && \
    rm -rf /tmp/rvc

COPY app.py rvc_infer.py ./

# Models directory — mount or copy .pth + .index files here
VOLUME /models

# CSO #3 — drop root. RVC reads models from /models (operator-managed
# read-only mount in practice). The A10 checksum verifier reads the
# sidecar .sha256 alongside each .pth, no writes needed. GPU access
# (/dev/nvidia*) is granted by the nvidia container runtime
# regardless of in-container uid — no root required. If you bind-
# mount /models from a host dir, the host dir needs to be world-
# readable OR owned by uid 1000.
RUN if ! id -u 1000 >/dev/null 2>&1; then \
        useradd -u 1000 -m -s /bin/bash gpu; \
    fi && chown -R 1000:1000 /app
USER 1000

EXPOSE 3016

CMD ["python3", "app.py"]
