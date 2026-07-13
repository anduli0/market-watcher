#!/bin/sh
set -e

# ── Claude CLI authentication ────────────────────────────────────────────────
# The AI 수석 브리프 shells out to `claude -p`, which authenticates via (priority):
# CLAUDE_CODE_OAUTH_TOKEN, ANTHROPIC_API_KEY, or ~/.claude/.credentials.json.
# Configure exactly ONE in the Render env. The subscription OAuth token is preferred
# so the deployed site bills the Max subscription, not a metered API key.
if [ -n "$CLAUDE_CODE_OAUTH_TOKEN" ]; then
    echo "[entrypoint] Claude auth: CLAUDE_CODE_OAUTH_TOKEN (long-lived OAuth token)"
elif [ -n "$ANTHROPIC_API_KEY" ]; then
    echo "[entrypoint] Claude auth: ANTHROPIC_API_KEY"
elif [ -n "$CLAUDE_CREDENTIALS" ]; then
    mkdir -p /root/.claude
    printf '%s' "$CLAUDE_CREDENTIALS" > /root/.claude/.credentials.json
    chmod 600 /root/.claude/.credentials.json
    echo "[entrypoint] Claude auth: restored ~/.claude/.credentials.json from CLAUDE_CREDENTIALS"
else
    echo "[entrypoint] WARNING: no Claude credential set — the AI brief will be unavailable"
    echo "[entrypoint]   (deterministic dashboard still works). Set CLAUDE_CODE_OAUTH_TOKEN."
fi

# main.py (apps/api) does `from autopilot.api.app import app`; PYTHONPATH already has src.
exec python -m uvicorn main:app --app-dir apps/api --host 0.0.0.0 --port "${PORT:-8000}"
