# market-watcher (MARKET WATCHER) — FastAPI dashboard + Claude Code CLI for the AI brief.
# Cloud-hosted on Render so the /market site is reachable from mobile INDEPENDENTLY of
# the owner's PC. The deterministic pipeline (keyless Yahoo/FRED + sibling watchers)
# always runs; the AI 수석 브리프 shells out to `claude -p` using the Max subscription
# OAuth token (CLAUDE_CODE_OAUTH_TOKEN), same pattern as the fed/krw watchers.
FROM python:3.13-slim

# Node.js for the `claude` CLI
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code --no-audit --no-fund

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# autopilot package lives under src/; the ASGI entrypoint is apps/api/main.py.
ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

RUN mkdir -p /app/data \
    && sed -i 's/\r$//' /app/docker-entrypoint.sh && chmod +x /app/docker-entrypoint.sh

EXPOSE 8000
CMD ["/bin/sh", "/app/docker-entrypoint.sh"]
