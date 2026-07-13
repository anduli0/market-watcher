"""PipelineService: the READ_ONLY analytical pipeline — collect signals -> regime ->
Meta-CIO -> cross-asset allocation -> analyst report -> instrument translation ->
risk decisions. Produces NO orders.

Serving model = stale-while-revalidate: the dashboard always gets the last good result
instantly; staleness triggers a background refresh. The first-ever request is bounded so
the page never hangs (degrades to a 'warming up' result and fills in shortly).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import yaml

from autopilot.adapters.accuracy import collect_accuracy
from autopilot.adapters.collector import SignalSnapshot, WatcherSpec, build_adapters, collect
from autopilot.adapters.delegates import collect_intel
from autopilot.adapters.news import collect_news
from autopilot.config import Settings
from autopilot.domain.allocation.engine import build_portfolio
from autopilot.domain.allocation.schemas import CrossAssetPortfolio
from autopilot.domain.cio.engine import decide
from autopilot.domain.cio.schemas import CioDecision
from autopilot.domain.enums import AppMode, Watcher
from autopilot.domain.execution.intents import IntentProposal, build_proposals
from autopilot.domain.execution.schemas import (
    KillSwitchState,
    RiskContext,
    RiskDecision,
    RiskLimits,
)
from autopilot.domain.geopolitics.engine import build_geo_view
from autopilot.domain.geopolitics.schemas import GeoView
from autopilot.domain.instruments.registry import InstrumentRegistry
from autopilot.domain.newsbrief.engine import build_news_brief
from autopilot.domain.newsbrief.schemas import NewsBrief
from autopilot.domain.orchestration.engine import build_world_view
from autopilot.domain.orchestration.schemas import WatcherIntel, WorldView
from autopilot.domain.realestate.archive import update_and_load
from autopilot.domain.realestate.engine import (
    RE_NEWS_KEYWORDS,
    build_realestate_view,
    select_kr_redev,
    select_us_markets,
)
from autopilot.domain.realestate.schemas import RealEstateView
from autopilot.domain.regime.engine import assess_regime
from autopilot.domain.regime.schemas import RegimeAssessment
from autopilot.domain.report.analyst import build_report
from autopilot.domain.report.schemas import AnalystReport
from autopilot.domain.risk.engine import RiskEngine, load_limits
from autopilot.domain.risk.kill_switch import KillSwitch
from autopilot.domain.synthesis.engine import build_synthesis
from autopilot.domain.synthesis.schemas import MarketSynthesis
from autopilot.domain.time import now_utc, to_kst
from autopilot.domain.track.engine import calibrate_confidence
from autopilot.track import TrackService

_WATCHER_ENV = {
    "fed_watcher": (Watcher.FED_WATCHER, "fed_watcher_base_url"),
    "krw_watcher": (Watcher.KRW_WATCHER, "krw_watcher_base_url"),
    "kospi_watcher": (Watcher.KOSPI_WATCHER, "kospi_watcher_base_url"),
    "us_watcher": (Watcher.US_WATCHER, "us_watcher_base_url"),
}


def load_watcher_specs(settings: Settings) -> dict[Watcher, WatcherSpec]:
    raw: dict[str, Any] = yaml.safe_load(
        (settings.config_dir / "watchers.yml").read_text(encoding="utf-8")
    )
    specs: dict[Watcher, WatcherSpec] = {}
    for key, (watcher, attr) in _WATCHER_ENV.items():
        cfg = raw.get(key, {})
        specs[watcher] = WatcherSpec(
            base_url=getattr(settings, attr),
            ttl_seconds=int(cfg.get("ttl_seconds", 43200)),
            max_age_seconds=int(cfg.get("max_age_seconds", 129600)),
            enabled=bool(cfg.get("enabled", True)),
        )
    return specs


@dataclass
class PipelineResult:
    as_of: datetime
    mode: AppMode
    live_armed: bool
    kill_switch: KillSwitchState
    snapshot: SignalSnapshot
    regime: RegimeAssessment
    cio: CioDecision
    proposals: list[IntentProposal]
    decisions: dict[str, RiskDecision]
    limits: RiskLimits
    portfolio: CrossAssetPortfolio
    report: AnalystReport
    news: list[tuple[str, str]]
    synthesis: MarketSynthesis
    realestate: RealEstateView
    geopolitics: GeoView
    world_view: WorldView
    news_brief: NewsBrief
    warming: bool = False


class PipelineService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.specs = load_watcher_specs(settings)
        self.registry = InstrumentRegistry.from_yaml(settings.config_dir / "instruments.yml")
        self.limits = load_limits(settings.config_dir / "risk_limits.yml")
        self.kill_switch = KillSwitch(settings.data_dir / "kill_switch.json")
        self.track = TrackService(settings)
        self._cache: PipelineResult | None = None
        self._cache_at: datetime | None = None
        self._refreshing = False
        self._bg: set[asyncio.Task[None]] = set()

    def _base_urls(self) -> dict[str, str]:
        return {
            "fed_watcher_base_url": self.settings.fed_watcher_base_url,
            "krw_watcher_base_url": self.settings.krw_watcher_base_url,
            "kospi_watcher_base_url": self.settings.kospi_watcher_base_url,
            "us_watcher_base_url": self.settings.us_watcher_base_url,
        }

    def _assemble(
        self,
        snap: SignalSnapshot,
        news: list[tuple[str, str]],
        intel: list[WatcherIntel],
        accuracy: dict[Watcher, float],
        *,
        warming: bool,
    ) -> PipelineResult:
        fresh = snap.fresh(snap.collected_at)
        regime = assess_regime(fresh, as_of=snap.collected_at)
        # Own-track-record feedback: once enough scored outcomes exist, displayed
        # confidence is nudged toward the realized hit rate (bounded ±0.15,
        # sample-gated) — persistent over/under-confidence self-corrects.
        cal = self.track.calibration()
        if cal is not None:
            adjusted = calibrate_confidence(
                regime.confidence,
                hit_rate=cal["hit_rate"],
                avg_stated_confidence=cal["avg_stated_confidence"],
                n_directional=cal["n_directional"],
            )
            if adjusted != regime.confidence:
                regime = regime.model_copy(update={"confidence": round(adjusted, 4)})
        cio = decide(regime, fresh, accuracy)
        portfolio = build_portfolio(regime, fresh)
        report = build_report(portfolio, regime, cio, fresh, news)
        synthesis = build_synthesis(regime, fresh)
        today = to_kst(snap.collected_at).date()
        us_markets = select_us_markets(today.toordinal())
        us_archive = tuple(
            update_and_load(
                self.settings.data_dir / "realestate_us_archive.json",
                today.isoformat(),
                [(m.region, m.best_for) for m in us_markets],
            )
        )
        re_news = tuple(
            txt for _src, txt in news if any(k.lower() in txt.lower() for k in RE_NEWS_KEYWORDS)
        )
        realestate = build_realestate_view(
            regime,
            fresh,
            korea_stance=self.settings.korea_rate_stance,
            korea_hikes=self.settings.korea_expected_hikes,
            us_markets=us_markets,
            us_archive=us_archive,
            re_news=re_news,
            kr_redev=select_kr_redev(today.toordinal()),
        )
        geopolitics = build_geo_view(regime, fresh)
        world_view = build_world_view(regime, fresh, intel)
        news_brief = build_news_brief(
            news, regime, world_view.converged_risk_on, world_view.headline
        )
        proposals = build_proposals(
            cio,
            self.registry,
            allowed_instruments=set(self.limits.allowed_instruments),
            as_of=snap.collected_at,
        )
        ks = self.kill_switch.state()
        engine = RiskEngine(self.limits)
        ctx = RiskContext(
            as_of=snap.collected_at,
            app_mode=self.settings.app_mode,
            kill_switch_engaged=ks.engaged,
            market_open=None,
            watcher_fresh=snap.coverage > 0,
        )
        decisions = {
            p.intent.intent_id: engine.evaluate(p.intent, ctx)
            for p in proposals
            if p.intent is not None
        }
        return PipelineResult(
            as_of=snap.collected_at,
            mode=self.settings.app_mode,
            live_armed=self.settings.live_armed,
            kill_switch=ks,
            snapshot=snap,
            regime=regime,
            cio=cio,
            proposals=proposals,
            decisions=decisions,
            limits=self.limits,
            portfolio=portfolio,
            report=report,
            news=news,
            synthesis=synthesis,
            realestate=realestate,
            geopolitics=geopolitics,
            world_view=world_view,
            news_brief=news_brief,
            warming=warming,
        )

    async def _compute(self) -> PipelineResult:
        snap = await collect(build_adapters(self.specs))
        news = await collect_news(self._base_urls())
        intel = await collect_intel(self._base_urls(), snap.fresh(snap.collected_at))
        accuracy = await collect_accuracy(self._base_urls())
        return self._assemble(snap, news, intel, accuracy, warming=False)

    async def _refresh(self) -> None:
        if self._refreshing:
            return
        self._refreshing = True
        try:
            result = await self._compute()
            self._cache = result
            self._cache_at = now_utc()
            self.track.record(result)  # upsert today's recommendation (KST day)
            self._spawn(self.track.refresh_scores())  # 6h-cached realized scoring
        except Exception:  # noqa: BLE001 — keep last good on any refresh failure
            pass
        finally:
            self._refreshing = False

    def _spawn(self, coro: Any) -> None:
        task: asyncio.Task[None] = asyncio.create_task(coro)
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    def warm(self) -> None:
        """Fire-and-forget cache warm (call at startup)."""
        self._spawn(self._refresh())

    async def run(self, *, use_cache: bool = True) -> PipelineResult:
        now = now_utc()
        if self._cache is None:
            # Never block the first request: start a refresh and serve a 'warming' result.
            if not self._refreshing:
                self._spawn(self._refresh())
            return self._degraded(now)
        age = (now - self._cache_at).total_seconds() if self._cache_at else 1e9
        if use_cache and age > self.settings.pipeline_cache_seconds and not self._refreshing:
            self._spawn(self._refresh())  # stale-while-revalidate (non-blocking)
        self._cache.kill_switch = self.kill_switch.state()
        return self._cache

    def _degraded(self, now: datetime) -> PipelineResult:
        snap = SignalSnapshot(collected_at=now, signals=[])
        return self._assemble(snap, [], [], {}, warming=True)
