"""Private dashboard API (READ_ONLY). Serves the integrated pipeline state and the
single-page dashboard. No order-submission endpoint exists — live execution is not
implemented. The kill-switch mutators require an admin key (disabled if unset)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse

from autopilot.config import Settings
from autopilot.domain.enums import regime_ko
from autopilot.domain.execution.schemas import KillSwitchState
from autopilot.domain.time import to_kst
from autopilot.llm.service import AiBriefService
from autopilot.pipeline import PipelineResult, PipelineService

_STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    app.state.settings = settings
    app.state.pipeline = PipelineService(settings)
    app.state.pipeline.warm()  # background cache warm so the first dashboard hit is fast
    app.state.aibrief = AiBriefService(settings, app.state.pipeline)
    app.state.aibrief.start()  # website-driven AI brief: server-side auto refresh
    yield
    await app.state.aibrief.stop()


app = FastAPI(title="MARKET WATCHER", version="0.2.0", lifespan=lifespan)


# Public mount prefix for sub-path exposure (e.g. Tailscale Funnel multiplexes several
# apps on one HTTPS port by path). Empty string => root-only (local) behaviour.
_PUBLIC_PREFIX = os.environ.get("AUTOPILOT_PUBLIC_PREFIX", "/market").rstrip("/")


class _SubPathMiddleware:
    """Serve the same app at the site root *and* under a sub-path like ``/market``.

    Tailscale Funnel routes by path prefix and forwards the path unchanged (it does not
    strip the prefix). This strips the configured prefix from the incoming ASGI path so
    the routes below match whether a request arrives as ``/market/api/v1/state`` (funnel)
    or ``/api/v1/state`` (local 127.0.0.1:8200). Harmless if the proxy already stripped it.
    The MARKET WATCHER ↔ four-watcher integration is untouched — this only affects routing.
    """

    def __init__(self, app: Any, prefix: str) -> None:
        self._app = app
        self._prefix = prefix

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if self._prefix and scope.get("type") in ("http", "websocket"):
            path: str = scope.get("path", "")
            if path == self._prefix or path.startswith(self._prefix + "/"):
                scope = dict(scope)
                scope["path"] = path[len(self._prefix) :] or "/"
                scope["root_path"] = self._prefix
        await self._app(scope, receive, send)


if _PUBLIC_PREFIX:
    app.add_middleware(_SubPathMiddleware, prefix=_PUBLIC_PREFIX)


def _sig(s: Any, now: Any) -> dict[str, Any]:
    return {
        "watcher": s.watcher.value,
        "target": s.target,
        "horizon": s.horizon.value,
        "direction": s.direction.value,
        "confidence": round(s.confidence, 3),
        "regime": s.regime,
        "expected_move": str(s.expected_move) if s.expected_move is not None else None,
        "unit": s.expected_move_unit.value if s.expected_move_unit else None,
        "data_quality": round(s.data_quality.overall, 2),
        "age_seconds": round(s.data_age_seconds(now)),
        "stale": s.is_stale(now),
    }


def _prop(p: Any, decision: Any) -> dict[str, Any]:
    d = None
    if decision is not None:
        d = {
            "status": decision.status.value,
            "failed_checks": [c.value for c in decision.failed_checks],
            "reason": decision.reason,
            "requires_human": decision.requires_human,
        }
    return {
        "exposure": p.exposure,
        "direction": p.direction.value,
        "chosen_ticker": p.translation.chosen.ticker if p.translation.chosen else None,
        "chosen_name": p.translation.chosen.name_ko if p.translation.chosen else None,
        "tradable": p.translation.tradable,
        "reasons": list(p.translation.reasons),
        "decision": d,
    }


def _serialize(r: PipelineResult) -> dict[str, Any]:
    snap = r.snapshot
    reg = r.regime
    top_probs = dict(sorted(reg.regime_probabilities.items(), key=lambda kv: -kv[1])[:6])
    return {
        "as_of_utc": r.as_of.isoformat(),
        "as_of_kst": to_kst(r.as_of).isoformat(),
        "warming": r.warming,
        "mode": r.mode.value,
        "live_armed": r.live_armed,
        "kill_switch": r.kill_switch.model_dump(mode="json"),
        "watchers": {
            "coverage": round(snap.coverage, 2),
            "health": {w.value: ok for w, ok in snap.health.items()},
            "errors": {w.value: e for w, e in snap.errors.items()},
        },
        "signals": [_sig(s, r.as_of) for s in snap.signals],
        "regime": {
            "primary": reg.primary_regime.value,
            "primary_ko": regime_ko(reg.primary_regime),
            "secondary": reg.secondary_regime.value if reg.secondary_regime else None,
            "secondary_ko": regime_ko(reg.secondary_regime) if reg.secondary_regime else None,
            "confidence": round(reg.confidence, 3),
            "coverage": round(reg.coverage, 2),
            "transition_risk": round(reg.transition_risk, 2),
            "probabilities": top_probs,
            "supporting": list(reg.supporting_signals),
            "contradictory": list(reg.contradictory_signals),
            "invalidations": [ic.model_dump(mode="json") for ic in reg.invalidation_conditions],
            "yield_decomposition": reg.yield_decomposition.model_dump(mode="json"),
        },
        "cio": {
            "strategy_brief": r.cio.strategy_brief,
            "risk_on_score": r.cio.risk_on_score,
            "target_cash_ratio": r.cio.target_cash_ratio,
            "asset_class_allocation": r.cio.asset_class_allocation,
            "country_allocation": r.cio.country_allocation,
            "style_tilts": r.cio.style_tilts,
            "sector_tilts": r.cio.sector_tilts,
            "portfolio_confidence": r.cio.portfolio_confidence,
            "watcher_weights": [
                {"watcher": w.watcher.value, "weight": w.weight, "components": w.components}
                for w in r.cio.watcher_weights
            ],
            "disagreements": list(r.cio.disagreements),
        },
        "proposals": [
            _prop(p, r.decisions.get(p.intent.intent_id) if p.intent else None) for p in r.proposals
        ],
        "limits": {
            "allowed_instruments": len(r.limits.allowed_instruments),
            "allowed_strategies": len(r.limits.allowed_strategies),
            "market_open": r.limits.market_open,
        },
        "portfolio": {
            "headline": r.portfolio.headline,
            "risk_on_score": r.portfolio.risk_on_score,
            "confidence": r.portfolio.confidence,
            "coverage": r.portfolio.coverage,
            "notes": list(r.portfolio.notes),
            "allocations": [
                {
                    "asset": a.asset.value,
                    "label_ko": a.label_ko,
                    "weight": a.weight,
                    "neutral_weight": a.neutral_weight,
                    "stance": a.stance,
                    "score": a.score,
                    "rationale": a.rationale,
                    "drivers": list(a.drivers),
                }
                for a in r.portfolio.allocations
            ],
        },
        "report": {
            "title": r.report.title,
            "headline": r.report.headline,
            "summary": r.report.summary,
            "sections": [
                {"heading": s.heading, "body": s.body, "bullets": list(s.bullets)}
                for s in r.report.sections
            ],
            "markdown": r.report.to_markdown(),
        },
        "news": [{"source": src, "text": txt} for src, txt in r.news],
        "synthesis": {
            "headline": r.synthesis.headline,
            "bottom_line": r.synthesis.bottom_line,
            "takeaways": [
                {
                    "watcher": t.watcher.value,
                    "label_ko": t.label_ko,
                    "present": t.present,
                    "standalone": t.standalone,
                    "in_context": t.in_context,
                }
                for t in r.synthesis.takeaways
            ],
            "insights": [
                {"kind": i.kind, "title": i.title, "detail": i.detail} for i in r.synthesis.insights
            ],
        },
        "realestate": r.realestate.model_dump(mode="json"),
        "geopolitics": r.geopolitics.model_dump(mode="json"),
        "world_view": {
            "headline": r.world_view.headline,
            "overview": r.world_view.overview,
            "bottom_line": r.world_view.bottom_line,
            "converged_risk_on": r.world_view.converged_risk_on,
            "confidence": r.world_view.confidence,
            "converged": r.world_view.converged,
            "iterations": r.world_view.iterations,
            "desks": [d.model_dump(mode="json") for d in r.world_view.desks],
            "consensus": list(r.world_view.consensus),
            "dissent": list(r.world_view.dissent),
            "rounds": [rd.model_dump(mode="json") for rd in r.world_view.rounds],
            "intel": [i.model_dump(mode="json") for i in r.world_view.intel],
        },
        "news_brief": r.news_brief.model_dump(mode="json"),
    }


@app.get("/health")
async def health(request: Request) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    return {"status": "ok", "mode": settings.app_mode.value, "live_armed": settings.live_armed}


@app.get("/api/v1/state")
async def state(request: Request) -> dict[str, Any]:
    result: PipelineResult = await request.app.state.pipeline.run()
    return _serialize(result)


@app.get("/api/v1/track")
async def track(request: Request) -> dict[str, Any]:
    """Own track record: recorded recommendations scored against realized KRW-view
    returns. Refresh respects a 6h cache, so only the first stale hit pays for the
    price fetch."""
    pipeline: PipelineService = request.app.state.pipeline
    await pipeline.track.refresh_scores()
    return pipeline.track.report()


@app.get("/api/v1/aibrief")
async def aibrief(request: Request) -> dict[str, Any]:
    svc: AiBriefService = request.app.state.aibrief
    return {"status": svc.status(), "brief": svc.brief()}


@app.post("/api/v1/aibrief/run")
async def aibrief_run(request: Request) -> dict[str, Any]:
    """Dashboard-triggered generation. Unauthenticated by design (read-only analytics
    site); abuse is bounded by the min-interval + daily cap inside the service."""
    svc: AiBriefService = request.app.state.aibrief
    out = await svc.run(force=True, trigger="dashboard")
    return {**out, "status": svc.status()}


def _require_admin(request: Request, x_admin_key: str | None) -> None:
    settings: Settings = request.app.state.settings
    if not settings.admin_api_key:
        raise HTTPException(503, "kill-switch mutation disabled (no ADMIN_API_KEY set)")
    if x_admin_key != settings.admin_api_key:
        raise HTTPException(401, "invalid admin key")


@app.post("/api/v1/kill-switch/engage")
async def engage(
    request: Request, x_admin_key: str | None = Header(default=None)
) -> dict[str, Any]:
    _require_admin(request, x_admin_key)
    ks: KillSwitchState = request.app.state.pipeline.kill_switch.engage(
        "manual engage via dashboard", "dashboard"
    )
    return ks.model_dump(mode="json")


@app.post("/api/v1/kill-switch/clear")
async def clear(request: Request, x_admin_key: str | None = Header(default=None)) -> dict[str, Any]:
    _require_admin(request, x_admin_key)
    ks: KillSwitchState = request.app.state.pipeline.kill_switch.clear("dashboard")
    return ks.model_dump(mode="json")


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    # no-store so browsers always load the latest UI (avoids stale cached dashboards).
    return HTMLResponse(
        (_STATIC / "index.html").read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store, must-revalidate"},
    )
