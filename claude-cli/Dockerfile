# syntax=docker/dockerfile:1
#
# Claude Code CLI + OpenAI-compatible HTTP wrapper, in one non-root
# container. Deployed per GPU server (like Ollama); the bob agent
# discovers it via CLAUDE_CLI_URL and reports its models to the
# control plane. See README.md.

FROM node:22-bookworm-slim

# Runtime deps:
#   ca-certificates - TLS to api.anthropic.com
#   python3 + venv  - the FastAPI wrapper
#   tini            - proper PID 1 (signal handling + zombie reaping)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        python3 \
        python3-venv \
        tini \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code globally.
# WORKDIR is set to a small dir BEFORE install so the installer does not
# scan the whole filesystem (a known cause of OOM/hangs when running as root).
WORKDIR /tmp
RUN npm install -g @anthropic-ai/claude-code \
    && npm cache clean --force

# Wrapper venv (kept off the node image's system python).
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir fastapi 'uvicorn[standard]'

# Run as an unprivileged user. Home dir is stable so a mounted volume on
# ~/.claude persists CLI config across restarts.
RUN useradd --create-home --shell /bin/bash claude
COPY app/main.py /opt/app/main.py
USER claude
WORKDIR /home/claude

EXPOSE 3021

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/opt/venv/bin/uvicorn", "main:app", "--app-dir", "/opt/app", "--host", "0.0.0.0", "--port", "3021"]
