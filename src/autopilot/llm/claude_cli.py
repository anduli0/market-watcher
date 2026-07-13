"""Headless `claude -p` runner (operator's Claude Max subscription — NOT an API key).

The web server invokes this directly, so the AI analysis is website-driven: phones
just open the dashboard. Headless auth is enabled once via `claude setup-token`
(or by saving that token into ``data/claude_oauth_token.txt``); until then callers
get :class:`ClaudeAuthError` and the deterministic platform output is unaffected.

The prompt is passed via STDIN (not argv) to avoid Windows argv length/encoding
limits with long Korean prompts.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any


class ClaudeUnavailableError(RuntimeError):
    """CLI missing, crashed, or timed out (not an auth problem)."""


class ClaudeAuthError(RuntimeError):
    """Headless subscription auth unavailable — run `claude setup-token` once."""


# Variables that would misroute a headless child invocation (e.g. a session-scoped
# proxy inherited from a parent Claude Code session, or a dead watcher SDK key).
_SCRUB_ENV = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
    "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_CODE_CHILD_SESSION",
    "CLAUDE_CODE_SDK_HAS_HOST_AUTH_REFRESH",
    "CLAUDE_CODE_OAUTH_SCOPES",
    "CLAUDE_CODE_ENTRYPOINT",
)

_AUTH_MARKERS = ("401", "authenticate", "credential", "setup-token", "not logged in")

TOKEN_FILENAME = "claude_oauth_token.txt"


def find_cli() -> str | None:
    return shutil.which("claude")


def build_env(data_dir: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _SCRUB_ENV}
    token = ""
    with contextlib.suppress(OSError):
        token = (data_dir / TOKEN_FILENAME).read_text(encoding="utf-8").strip()
    if token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token  # output of `claude setup-token`
    return env


def _classify_failure(returncode: int | None, out: str, err: str) -> Exception:
    blob = f"{out}\n{err}".lower()
    if any(m in blob for m in _AUTH_MARKERS):
        return ClaudeAuthError(f"claude headless auth failed: {(err or out)[:200]}")
    return ClaudeUnavailableError(f"claude -p failed (rc={returncode}): {(err or out)[:200]}")


async def run_prompt(
    prompt: str, *, model: str, timeout_seconds: int, data_dir: Path
) -> str:
    """Run one headless synthesis; return the model's text (the ``result`` field).

    Hardened for constrained container hosts (Render free tier), mirroring the
    proven krw-watcher runner:
      * ``--output-format json`` — parse the JSON envelope on STDOUT; ``claude -p``
        can exit NON-ZERO even on full success (post-response cleanup), so we trust
        a well-formed non-error result regardless of the exit code. Treating a
        non-zero exit as failure is what could make a cloud brief look "auth-failed"
        when it had actually succeeded.
      * ``cwd`` = a temp dir outside any git repo so folder-trust / repo hooks
        don't block a non-interactive run.
      * capped Node V8 heap so a 512 MB host doesn't OOM-kill the CLI mid-run.
    """
    exe = find_cli()
    if exe is None:
        raise ClaudeUnavailableError("claude CLI not found in PATH")

    env = build_env(data_dir)
    node_opts = env.get("NODE_OPTIONS", "")
    if "max-old-space-size" not in node_opts:
        heap = os.environ.get("CLAUDE_NODE_MAX_OLD_SPACE_MB", "256")
        env["NODE_OPTIONS"] = f"{node_opts} --max-old-space-size={heap}".strip()

    proc = await asyncio.create_subprocess_exec(
        exe,
        "-p",
        "--model",
        model,
        "--output-format",
        "json",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=tempfile.gettempdir(),
        env=env,
    )
    try:
        out_b, err_b = await asyncio.wait_for(
            proc.communicate(prompt.encode("utf-8")), timeout_seconds
        )
    except TimeoutError:
        proc.kill()
        with contextlib.suppress(Exception):
            await proc.communicate()
        raise ClaudeUnavailableError(f"claude -p timed out after {timeout_seconds}s") from None

    out = (out_b or b"").decode("utf-8", "replace").strip()
    err = (err_b or b"").decode("utf-8", "replace").strip()

    # Parse the JSON envelope first; trust a good result whatever the exit code was.
    data: Any = None
    if out:
        with contextlib.suppress(json.JSONDecodeError):
            data = json.loads(out)
    if isinstance(data, dict):
        if data.get("is_error"):
            msg = str(data.get("result") or data.get("error") or "")
            api_err = data.get("api_error_status")
            blob = f"{msg} {api_err}".lower()
            if api_err in (401, 403) or any(m in blob for m in _AUTH_MARKERS):
                raise ClaudeAuthError(f"claude headless auth failed: {msg[:200]}")
            raise ClaudeUnavailableError(f"claude -p error: {msg[:200]}")
        result = data.get("result")
        if isinstance(result, str) and (result.strip() or data.get("subtype") == "success"):
            return result
        # well-formed envelope but empty result — fall through to failure below

    # No usable JSON result: classify by markers (auth vs transient) and raise.
    raise _classify_failure(proc.returncode, out, err)


def extract_json(text: str) -> dict[str, Any]:
    """First-{ .. last-} JSON object from model output (models may add prose)."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"no JSON object in claude output: {text[:160]!r}")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("claude output JSON is not an object")
    return data
