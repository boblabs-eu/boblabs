FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    procps \
    lm-sensors \
    ufw \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# CSO #3 — drop root for the agent container. Aligns the container
# posture with the bare-metal install (install.sh creates a non-root
# bob-agent user). The collectors already handle psutil.AccessDenied
# gracefully (ports.py:23, network.py:52, processes.py:32) so non-root
# means some per-process / cross-user metrics become unavailable —
# acceptable trade-off for not running as root. Port 9100 is
# non-privileged, so binding works fine.
#
# Note: the Docker collector inside the container is already a no-op
# because docker-compose.agent.yml doesn't mount the docker socket —
# so dropping root has no impact on that collector path either way.
RUN if ! id -u 1000 >/dev/null 2>&1; then \
        useradd -u 1000 -m -s /bin/bash bobagent; \
    fi && chown -R 1000:1000 /app
USER 1000

EXPOSE 9100

CMD ["python", "-m", "app.main"]
