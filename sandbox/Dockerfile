FROM python:3.12-slim

WORKDIR /app

# System deps for CadQuery (OpenCASCADE) + general build tools + Chromium runtime libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libgl1 libglu1-mesa libx11-6 libxext6 libxmu6 libxi6 \
    jq bc curl wget ffmpeg \
    # Chromium runtime deps for Playwright headless_shell
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libpango-1.0-0 libcairo2 libasound2 libatspi2.0-0 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# CSO #3 — install Playwright browsers to a shared path that any USER
# can read, so the non-root user added below can still launch chromium.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
RUN python -m playwright install chromium

COPY main.py .

# CSO #3 — drop root inside the sandbox container. This is the highest-
# impact USER fix in the stack because the sandbox IS the untrusted
# code-execution boundary; any future python_exec / shell_exec escape
# now lands as uid 1000, not root. The lab_resources bind mount needs
# matching ownership — on a fresh deploy the volume inherits 1000:1000
# from the first write. For existing deployments, the operator must
# run once before redeploy:
#   docker run --rm -v bob-manager_lab_resources:/data alpine:3.20 \
#     chown -R 1000:1000 /data
# (deploy-prod.sh now does this automatically on every redeploy.)
RUN if ! id -u 1000 >/dev/null 2>&1; then \
        useradd -u 1000 -m -s /bin/bash sandbox; \
    fi && chown -R 1000:1000 /app
USER 1000

EXPOSE 9000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9000", "--workers", "1"]
