# bob-hermes-adapter — the real NousResearch Hermes agent + the HTTP adapter
# that the Bob Lab control-plane drives (contract: ADAPTER_CONTRACT.md).
#
# Build:  docker build -t bob-hermes-adapter:latest hermes-adapter/
# Wire:   HERMES_IMAGE=bob-hermes-adapter:latest in .env → restart bob-api
#
# hermes-agent requires Python >=3.11,<3.14. Pinned to the release verified
# against the adapter; bump deliberately and re-test /v1/agent/run.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/root

# Minimal system deps for Hermes' core tools (rg powers its file/search
# tools; git for repo work; ffmpeg/node are intentionally omitted — the
# corresponding tools degrade gracefully when their backend is missing).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ripgrep curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# The real Hermes (library entrypoint: run_agent.AIAgent). The [anthropic]
# extra enables Hermes' native anthropic api_mode for Claude models picked in
# the Bob Lab dropdown. fastapi/uvicorn ride pip's resolver alongside
# hermes-agent's own pins.
RUN pip install "hermes-agent[anthropic]==0.16.0" fastapi uvicorn

COPY adapter/main.py /opt/adapter/main.py

# Hermes state (memory, skills, sessions) — the control-plane mounts a
# persistent named volume here (bob-hermes-<agent-id>).
VOLUME /root/.hermes

EXPOSE 8770
CMD ["uvicorn", "main:app", "--app-dir", "/opt/adapter", "--host", "0.0.0.0", "--port", "8770"]
