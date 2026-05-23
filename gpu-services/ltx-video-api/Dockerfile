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

CMD ["python", "app.py"]
