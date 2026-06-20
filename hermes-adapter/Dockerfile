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

# System deps for Hermes' tools. rg powers file/search, git for repo work,
# ffmpeg backs the audio/video/media tools, Node.js 22 powers JS tooling.
#
# Hermes' KEYLESS web access = the `browser` toolset (browser_navigate/snapshot/
# click/…). Unlike `web_search`/`web_extract` (which need a paid Exa/Tavily key),
# the browser toolset needs NO API key — just the `agent-browser` CLI (npm,
# global) driving a local Chromium. Both are installed here so the browser tools
# light up out of the box. AGENT_BROWSER_EXECUTABLE_PATH (set below) points
# agent-browser at the system Chromium so it never downloads its own build.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git ripgrep curl ca-certificates gnupg xz-utils ffmpeg \
        chromium fonts-liberation \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g agent-browser \
    && npm cache clean --force \
    && rm -rf /var/lib/apt/lists/*

# Keyless local browser: agent-browser drives this system Chromium build.
ENV AGENT_BROWSER_EXECUTABLE_PATH=/usr/bin/chromium

# The real Hermes (library entrypoint: run_agent.AIAgent). The [anthropic]
# extra enables Hermes' native anthropic api_mode for Claude models picked in
# the Bob Lab dropdown. fastapi/uvicorn ride pip's resolver alongside
# hermes-agent's own pins.
RUN pip install "hermes-agent[anthropic]==0.16.0" fastapi uvicorn

# Native Hermes autonomy, in-adapter (placed AFTER the pip layer so editing it
# never busts the slow hermes-agent install cache on deploy rebuilds):
#  - HERMES_INTERACTIVE=1 unlocks the native `cronjob` tool (its
#    check_cronjob_requirements gates on this) so the agent can schedule tasks.
#  - TERMINAL_CWD pins the agent's working directory onto the persistent
#    ~/.hermes volume (the adapter mkdir's it at startup), so everything Hermes
#    builds — projects, renders, scripts — is durable AND captured, instead of
#    scattering to /tmp (invisible + wiped on container recreate).
#  - The tool caches are redirected under ~/.hermes so bun/npm/pip installs
#    survive a recreate instead of being rebuilt every time.
ENV HERMES_INTERACTIVE=1 \
    TERMINAL_CWD=/root/.hermes/workspace \
    BUN_INSTALL=/root/.hermes/cache/bun \
    npm_config_cache=/root/.hermes/cache/npm \
    PIP_CACHE_DIR=/root/.hermes/cache/pip \
    XDG_CACHE_HOME=/root/.hermes/cache \
    XDG_DATA_HOME=/root/.hermes/data

COPY adapter/main.py /opt/adapter/main.py

# Hermes state (memory, skills, sessions) — the control-plane mounts a
# persistent named volume here (bob-hermes-<agent-id>).
VOLUME /root/.hermes

EXPOSE 8770
CMD ["uvicorn", "main:app", "--app-dir", "/opt/adapter", "--host", "0.0.0.0", "--port", "8770"]
