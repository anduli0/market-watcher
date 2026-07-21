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

    site = ROOT / "site"
    shutil.rmtree(site, ignore_errors=True)
    api = site / "api" / "v1"
    shutil.copy(ROOT / "src" / "autopilot" / "api" / "static" / "index.html", _mk(site) / "index.html")
    (site / ".nojekyll").write_text("", encoding="utf-8")
    _write_json(api / "state", _serialize(result))
    _write_json(api / "track", pipeline.track.report())
    _write_json(api / "aibrief", {"status": status, "brief": ai.brief()})

    cov = result.snapshot.coverage
    print(f"site built: coverage={cov:.2f} regime={result.regime.primary_regime.value} "
          f"confidence={result.regime.confidence:.3f}")
    if cov <= 0.0:
        print("WARNING: watcher coverage is 0 — set *_WATCHER_BASE_URL to publicly "
              "reachable watcher URLs (repo Variables) for a fully-populated dashboard.")
    return 0


def _mk(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
