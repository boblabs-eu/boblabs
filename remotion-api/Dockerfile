FROM node:22-slim

# Install Chromium dependencies for Remotion headless rendering
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    fonts-liberation \
    fonts-noto-color-emoji \
    libgbm1 \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libxshmfence1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy package files and install dependencies
COPY package.json ./
RUN npm install --omit=dev

# Copy server
COPY server.mjs ./

ENV PORT=3020
ENV CHROMIUM_PATH=/usr/bin/chromium

# CSO #3 — drop root for remotion. The service writes render output to
# /tmp/remotion-<jobId>/ which is world-writable, and Chromium runs
# fine as a non-root user. node:22-slim already ships with a `node`
# user at uid 1000, so we reuse that instead of creating a duplicate
# (useradd -u 1000 would fail with "UID 1000 is not unique").
RUN if ! id -u 1000 >/dev/null 2>&1; then \
        useradd -u 1000 -m -s /bin/bash remotion; \
    fi && chown -R 1000:1000 /app
USER 1000

EXPOSE 3020

CMD ["node", "server.mjs"]
