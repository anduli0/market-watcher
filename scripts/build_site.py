"""Build a static GitHub Pages snapshot of the MARKET WATCHER dashboard.

Runs the full deterministic pipeline ONCE and writes the result as static files
that the unmodified dashboard (index.html) consumes at the exact same URLs the
live FastAPI server exposes:

    site/index.html
    site/api/v1/state      (JSON — same shape as GET /api/v1/state)
    site/api/v1/track      (JSON — same shape as GET /api/v1/track)
    site/api/v1/aibrief    (JSON — same shape as GET /api/v1/aibrief)

GitHub Actions runs this on a schedule, commits the updated data/ JSONs back
(track-record persistence), and deploys site/ to Pages. The dashboard then works
with zero server — the [AI 분석 실행] button is the only feature that needs a
live server (a static run_notice explains that).

AI brief: if the claude CLI + CLAUDE_CODE_OAUTH_TOKEN are available in the CI
environment, a brief is (re)generated under the service's own caps/dedupe;
otherwise the last stored brief is served as-is.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
# Windows consoles default to cp949 — keep progress prints from killing the build.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

from autopilot.api.app import _serialize  # noqa: E402 — reuse the live serializer
from autopilot.config import Settings  # noqa: E402
from autopilot.domain.time import now_utc  # noqa: E402
from autopilot.llm import claude_cli  # noqa: E402
from autopilot.llm.service import AiBriefService  # noqa: E402
from autopilot.pipeline import PipelineService  # noqa: E402

STATIC_NOTICE = (
    "정적 배포(GitHub Pages) — 수동 실행 버튼은 서버 모드에서만 동작합니다. "
    "브리프는 배포 주기마다 자동으로 재생성/갱신됩니다."
)

# ── KRW watcher mirror-cache ─────────────────────────────────────────────────
# fed/kospi/us watchers publish cloud-fresh static API mirrors (their own Actions
# pipelines), so this build consumes them directly. The KRW watcher has no cloud
# mirror (private repo, PC-hosted) — so: while its live URL answers, cache every
# consumed endpoint to data/krw_mirror.json (committed back); when it is
# unreachable, replay the cache from a localhost server. Payload timestamps are
# untouched, so the adapters' own TTL/staleness handling stays honest.
KRW_PATHS = ("/health", "/api/forecast", "/api/accuracy", "/api/briefing/latest", "/api/hierarchy")
_KRW_MIRROR_PORT = 18299


def _resolve_krw_base(data_dir: Path) -> str | None:
    import http.server
    import threading
    import urllib.request

    base = os.environ.get("KRW_WATCHER_BASE_URL", "http://127.0.0.1:8010").rstrip("/")
    mirror_path = data_dir / "krw_mirror.json"

    def fetch(path: str) -> Any | None:
        try:
            with urllib.request.urlopen(base + path, timeout=45) as r:
                return json.loads(r.read().decode("utf-8")) if r.status == 200 else None
        except Exception:  # noqa: BLE001 — reachability probe
            return None

    if fetch("/api/forecast") is not None:  # live source is up -> refresh the cache
        mirror = {p: body for p in KRW_PATHS if (body := fetch(p)) is not None}
        if mirror.get("/api/forecast") is not None:
            _write_json(mirror_path, mirror)
        print(f"krw: live ({base}) — mirror cached ({len(mirror)} endpoints)")
        return base

    try:
        mirror = json.loads(mirror_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        mirror = None
    if not isinstance(mirror, dict) or "/api/forecast" not in mirror:
        print("krw: unreachable and no mirror cache — KRW coverage will be 0")
        return None

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 — stdlib naming
            body = mirror.get(self.path.split("?")[0])
            data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else b"{}"
            self.send_response(200 if body is not None else 404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a: Any) -> None: ...

    server = http.server.ThreadingHTTPServer(("127.0.0.1", _KRW_MIRROR_PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"krw: unreachable — replaying mirror cache on :{_KRW_MIRROR_PORT} "
          "(source timestamps preserved; staleness handled by adapters)")
    return f"http://127.0.0.1:{_KRW_MIRROR_PORT}"


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


async def _maybe_generate_brief(ai: AiBriefService) -> None:
    """Generate a brief in CI only when the CLI + token exist; never fail the build."""
    if not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or claude_cli.find_cli() is None:
        print("aibrief: no CLI/token in environment — serving last stored brief")
        return
    out = await ai.run(force=False, trigger="pages-build")
    print(f"aibrief: started={out['started']} reason={out.get('reason')}")
    if out["started"]:
        await asyncio.gather(*ai._bg)  # noqa: SLF001 — wait for the spawned generation


async def main() -> int:
    krw_base = _resolve_krw_base(ROOT / "data")
    if krw_base:
        os.environ["KRW_WATCHER_BASE_URL"] = krw_base  # before Settings() reads env
    settings = Settings()
    pipeline = PipelineService(settings)

    result = await pipeline._compute()  # noqa: SLF001 — one direct synchronous-style run
    # Prime the service cache so AiBriefService._fresh_result() sees this result.
    pipeline._cache = result  # noqa: SLF001
    pipeline._cache_at = now_utc()  # noqa: SLF001

    pipeline.track.record(result)  # upsert today's recommendation
    await pipeline.track.refresh_scores(force=True)  # score against realized returns

    ai = AiBriefService(settings, pipeline)
    await _maybe_generate_brief(ai)
    status = ai.status()
    status["running"] = False
    status["run_notice"] = STATIC_NOTICE

    # Never regress the site to an empty dashboard: when the watchers are
    # unreachable (PC/funnel down -> coverage 0), serve the last GOOD serialized
    # state, which is committed back to the repo as data/state_snapshot.json.
    # Track scoring + AI brief above stay fresh either way (they don't need watchers).
    state = _serialize(result)
    cov = result.snapshot.coverage
    snap_path = settings.data_dir / "state_snapshot.json"
    if cov > 0.0:
        _write_json(snap_path, state)
    else:
        try:
            stored = json.loads(snap_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stored = None
        if isinstance(stored, dict) and stored.get("regime"):
            print(f"fallback: watchers unreachable — serving last good snapshot "
                  f"(기준 {stored.get('as_of_kst', '?')})")
            state = stored

    site = ROOT / "site"
    shutil.rmtree(site, ignore_errors=True)
    api = site / "api" / "v1"
    shutil.copy(ROOT / "src" / "autopilot" / "api" / "static" / "index.html", _mk(site) / "index.html")
    (site / ".nojekyll").write_text("", encoding="utf-8")
    _write_json(api / "state", state)
    _write_json(api / "track", pipeline.track.report())
    _write_json(api / "aibrief", {"status": status, "brief": ai.brief()})

    print(f"site built: coverage={cov:.2f} regime={state['regime']['primary']} "
          f"confidence={state['regime']['confidence']}")
    return 0


def _mk(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
