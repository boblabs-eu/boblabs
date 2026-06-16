FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium deps + browser for web tools.
# CSO #3 — install to /opt/playwright (world-readable) so the non-root
# user added below can launch chromium without re-installing.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libatspi2.0-0 \
    libcups2 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 \
    libpango-1.0-0 libcairo2 libasound2 libxshmfence1 libx11-xcb1 libxkbcommon0 \
    fonts-liberation fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/* \
    && playwright install chromium

COPY app/ ./app/
COPY alembic.ini ./

# CSO #3 — drop root for the control-plane process. bob-api writes to
# the lab_resources and qdrant_staging volumes (rw); both inherit
# 1000:1000 from the first write on a fresh deploy. For existing
# deployments, operator must chown the volumes once before redeploy:
#   docker run --rm -v bob-manager_lab_resources:/data alpine:3.20 \
#     chown -R 1000:1000 /data
#   docker run --rm -v bob-manager_qdrant_staging:/data alpine:3.20 \
#     chown -R 1000:1000 /data
# (deploy-prod.sh now does this automatically on every redeploy.)
# The bob-api process never needs to bind a privileged port (uvicorn
# on :8000) so dropping privileges is safe.
RUN if ! id -u 1000 >/dev/null 2>&1; then \
        useradd -u 1000 -m -s /bin/bash bobapi; \
    fi && chown -R 1000:1000 /app
USER 1000

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
