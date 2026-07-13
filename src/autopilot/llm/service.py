"""AiBriefService — the website runs Claude by itself.

The always-on FastAPI server (MarketWatcher-Server scheduled task) refreshes the AI
brief on a fixed cadence AND exposes a dashboard trigger, so any device (phone
included) just opens the site. No Claude Code session is involved at view time.

Token discipline (subscription-friendly):
- one compact KO call per generation (grounded on the deterministic pipeline)
- input-hash dedupe: unchanged market state -> no new call (auto runs)
- minimum interval between attempts + a hard daily cap
- persistent store survives restarts, so a good brief is never regenerated on boot
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from autopilot.config import Settings
from autopilot.domain.time import now_utc, to_kst
from autopilot.llm import claude_cli
from autopilot.llm.brief import (
    build_grounding,
    build_prompt,
    corrective_retry,
    grounding_hash,
    validate_brief,
)
from autopilot.pipeline import PipelineResult, PipelineService

AUTH_HELP = (
    "Claude 구독 인증이 필요합니다. PC 터미널에서 `claude setup-token`을 1회 실행하거나, "
    "발급된 토큰을 data/claude_oauth_token.txt 파일로 저장하면 자동으로 다시 켜집니다."
)


class AiBriefService:
    def __init__(
        self,
        settings: Settings,
        pipeline: PipelineService,
        *,
        store_path: Path | None = None,
    ) -> None:
        self.settings = settings
        self.pipeline = pipeline
        self._path = store_path or (settings.data_dir / "ai_brief.json")
        self._store: dict[str, Any] = self._load()
        self._running = False
        self._last_attempt: datetime | None = None
        self._last_auto: datetime | None = None
        self._auth_ok: bool | None = None if not self._store.get("brief") else True
        self._loop_task: asyncio.Task[None] | None = None
        self._bg: set[asyncio.Task[None]] = set()

    # ── persistence ──────────────────────────────────────────────────────────

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._store, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self._path)

    # ── status / reads ───────────────────────────────────────────────────────

    def _today_kst(self) -> str:
        return to_kst(now_utc()).date().isoformat()

    def _runs_today(self) -> int:
        runs = self._store.get("runs")
        if not isinstance(runs, dict):
            return 0
        n = runs.get(self._today_kst(), 0)
        return int(n) if isinstance(n, (int, float)) else 0

    def _count_run(self) -> None:
        today = self._today_kst()
        runs = self._store.get("runs")
        if not isinstance(runs, dict):
            runs = {}
        runs = {today: int(runs.get(today, 0)) + 1}  # prune old days
        self._store["runs"] = runs

    def brief(self) -> dict[str, Any] | None:
        b = self._store.get("brief")
        return b if isinstance(b, dict) else None

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.settings.llm_enabled,
            "cli_found": claude_cli.find_cli() is not None,
            "running": self._running,
            "auth_ok": self._auth_ok,
            "auth_help": AUTH_HELP if self._auth_ok is False else None,
            "model": self.settings.llm_model,
            "brief_date": self._store.get("date"),
            "generated_at_kst": self._store.get("generated_at_kst"),
            "trigger": self._store.get("trigger"),
            "runs_today": self._runs_today(),
            "daily_cap": self.settings.llm_daily_cap,
            "auto_minutes": self.settings.llm_auto_minutes,
            "min_interval_minutes": self.settings.llm_manual_min_minutes,
            "morning_hour_kst": self.settings.llm_morning_hour,
            "morning_done_date": self._store.get("morning_date"),
            "last_error": self._store.get("last_error"),
            "last_skip": self._store.get("last_skip"),
            "has_brief": self.brief() is not None,
        }

    # ── triggering ───────────────────────────────────────────────────────────

    async def run(self, *, force: bool, trigger: str) -> dict[str, Any]:
        """Start one generation in the background. Returns started/reason."""

        def skip(reason: str) -> dict[str, Any]:
            return {"started": False, "reason": reason}

        if not self.settings.llm_enabled:
            return skip("AI 브리프 기능이 설정에서 꺼져 있습니다 (LLM_ENABLED).")
        if claude_cli.find_cli() is None:
            return skip("서버에 claude CLI가 설치되어 있지 않습니다.")
        if self._running:
            return skip("이미 생성 중입니다. 잠시 후 자동으로 반영됩니다.")
        now = now_utc()
        min_s = self.settings.llm_manual_min_minutes * 60
        if self._last_attempt is not None and (now - self._last_attempt).total_seconds() < min_s:
            return skip(
                f"직전 실행 후 {self.settings.llm_manual_min_minutes}분이 지나야 "
                "다시 실행할 수 있습니다(토큰 보호)."
            )
        if self._runs_today() >= self.settings.llm_daily_cap:
            return skip(f"오늘 실행 한도({self.settings.llm_daily_cap}회)에 도달했습니다.")
        self._last_attempt = now
        self._running = True  # set before spawning so an immediate status() shows it
        task: asyncio.Task[None] = asyncio.create_task(
            self._generate(force=force, trigger=trigger)
        )
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)
        return {"started": True, "reason": None}

    async def _fresh_result(self) -> PipelineResult | None:
        for _ in range(30):
            r = await self.pipeline.run()
            if not r.warming:
                return r
            await asyncio.sleep(3)
        return None

    async def _generate(self, *, force: bool, trigger: str) -> None:
        try:
            r = await self._fresh_result()
            if r is None:
                self._store["last_error"] = "분석 파이프라인이 아직 준비 중입니다. 잠시 후 다시 시도하세요."
                self._save()
                return
            ih = grounding_hash(r)
            today = self._today_kst()
            if (
                not force
                and self.brief() is not None
                and self._store.get("input_hash") == ih
                and self._store.get("date") == today
            ):
                self._store["last_skip"] = "시장 데이터가 직전 생성 이후 변하지 않아 건너뛰었습니다."
                self._save()
                return
            self._count_run()
            self._save()
            prompt = build_prompt(build_grounding(r))
            kwargs: dict[str, Any] = {
                "model": self.settings.llm_model,
                "timeout_seconds": self.settings.llm_timeout_seconds,
                "data_dir": self.settings.data_dir,
            }
            try:
                out = await claude_cli.run_prompt(prompt, **kwargs)
                brief = validate_brief(claude_cli.extract_json(out))
            except (ValueError, json.JSONDecodeError) as e:  # one corrective retry
                out = await claude_cli.run_prompt(corrective_retry(prompt, e), **kwargs)
                brief = validate_brief(claude_cli.extract_json(out))
            self._auth_ok = True
            self._store.update(
                {
                    "brief": brief.model_dump(mode="json"),
                    "date": today,
                    "generated_at_kst": to_kst(now_utc()).isoformat(timespec="minutes"),
                    "model": self.settings.llm_model,
                    "input_hash": ih,
                    "trigger": trigger,
                    "last_error": None,
                    "last_skip": None,
                }
            )
            self._save()
        except claude_cli.ClaudeAuthError:
            self._auth_ok = False
            self._store["last_error"] = AUTH_HELP
            self._save()
        except Exception as e:  # noqa: BLE001 — must never take the server down
            self._store["last_error"] = f"{type(e).__name__}: {e}"[:300]
            self._save()
        finally:
            self._running = False

    # ── server-side auto refresh ─────────────────────────────────────────────

    def start(self) -> None:
        if self.settings.llm_enabled and self._loop_task is None:
            self._loop_task = asyncio.create_task(self._auto_loop())

    async def stop(self) -> None:
        if self._loop_task is not None:
            self._loop_task.cancel()
            self._loop_task = None

    async def _auto_loop(self) -> None:
        await asyncio.sleep(90)  # let the pipeline warm first
        while True:
            # the scheduler must survive anything short of cancellation
            with contextlib.suppress(Exception):
                await self._tick()
            await asyncio.sleep(300)  # 5-min decision tick (runs are gated inside)

    async def _tick(self) -> None:
        """One scheduler decision. The morning anchor comes first: a fresh brief every
        KST day at llm_morning_hour, and if the server slept through it (PC off,
        restart, outage) the first tick past the hour catches up immediately. The
        regular llm_auto_minutes cadence then keeps the brief current during the day."""
        now = now_utc()
        kst = to_kst(now)
        today = kst.date().isoformat()
        hour = self.settings.llm_morning_hour
        if 0 <= hour <= kst.hour and self._store.get("morning_date") != today:
            out = await self.run(force=True, trigger="morning")
            capped = self._runs_today() >= self.settings.llm_daily_cap
            if out["started"] or capped:  # else (busy/min-interval) retry next tick
                self._store["morning_date"] = today
                self._save()
            if out["started"]:
                self._last_auto = now
                return
        auto_s = self.settings.llm_auto_minutes * 60
        if self._last_auto is None or (now - self._last_auto).total_seconds() >= auto_s:
            self._last_auto = now
            await self.run(force=False, trigger="auto")
