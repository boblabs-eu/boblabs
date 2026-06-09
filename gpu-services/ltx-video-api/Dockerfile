FROM nvidia/cuda:12.8.1-devel-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-dev python3-venv \
        git ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --break-system-packages --no-cache-dir uv

# Clone LTX-2 monorepo and install via the official workspace method
# (uv sync resolves the workspace packages correctly, avoiding circular imports)
WORKDIR /opt/ltx-2
RUN git clone --depth 1 https://github.com/Lightricks/LTX-2.git .
RUN uv sync --frozen

# Install API dependencies into the same venv
RUN uv pip install fastapi 'uvicorn[standard]' pydantic 'python-multipart>=0.0.6'

# Copy our API wrapper
WORKDIR /app
COPY app.py .

EXPOSE 3018

ENV VIRTUAL_ENV=/opt/ltx-2/.venv
ENV PATH="/opt/ltx-2/.venv/bin:$PATH"
ENV PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility
ENV LTX_HOST=0.0.0.0
ENV LTX_PORT=3018

# CSO #3 — drop root. /opt/ltx-2 (the LTX-2 source + venv) was built as
# root with world-readable permissions; the non-root user can import
# from it without ownership changes. HuggingFace cache goes to /app
# so the user has write access for model downloads on first request.
ENV HF_HOME=/app/.cache/huggingface
ENV XDG_CACHE_HOME=/app/.cache
RUN if ! id -u 1000 >/dev/null 2>&1; then \
        useradd -u 1000 -m -s /bin/bash gpu; \
    fi && mkdir -p /app/.cache && chown -R 1000:1000 /app
USER 1000

CMD ["python", "app.py"]
