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

# Install Chromium browser binaries used by Playwright (no system deps via apt — already installed above)
RUN python -m playwright install chromium

COPY main.py .

EXPOSE 9000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9000", "--workers", "1"]
