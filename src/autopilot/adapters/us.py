"""US STOCK WATCHER adapter. Source: GET /api/v1/market/overview (OverviewResponse).

US equity market-state nowcast: `pulse.score` in [-100,+100], an 11-value regime,
`confidence` in 0..100, and `coverage` in 0..1 (fraction of regime components measured
-> completeness). `as_of` is aware-UTC. The score sign (with a neutral dead-band) maps
to direction.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from autopilot.adapters.base import WatcherAdapter, make_signal_id, quality
from autopilot.domain.enums import Horizon, MoveUnit, SignalDirection, Watcher
from autopilot.domain.signals.schemas import NormalizedSignal
from autopilot.domain.time import parse_iso_utc

# Neutral dead-band on the −100..+100 composite score.
US_SCORE_NEUTRAL_BAND = 10.0
_TARGET = "US_EQUITY"


class UsStockWatcherAdapter(WatcherAdapter):
    watcher = Watcher.US_WATCHER

    @property
    def latest_path(self) -> str:
        return "/api/v1/market/overview"

    @property
    def health_path(self) -> str:
        return "/health"

    @classmethod
    def parse(cls, body: Any, fetched_at: datetime, ttl_seconds: int) -> list[NormalizedSignal]:
        if not isinstance(body, dict) or "pulse" not in body or "as_of" not in body:
            raise ValueError("expected an OverviewResponse with a 'pulse'")
        pulse = body["pulse"]
        source_at = parse_iso_utc(body["as_of"])
        score = float(pulse["score"])
        if score > US_SCORE_NEUTRAL_BAND:
            direction = SignalDirection.UP
        elif score < -US_SCORE_NEUTRAL_BAND:
            direction = SignalDirection.DOWN
        else:
            direction = SignalDirection.NEUTRAL
        coverage = float(pulse.get("coverage", 1.0))
        return [
            NormalizedSignal(
                signal_id=make_signal_id(cls.watcher, _TARGET, Horizon.NOWCAST.value, source_at),
                watcher=cls.watcher,
                generated_at=fetched_at,
                source_data_at=source_at,
                model_version="us-v0",
                target=_TARGET,
                regime=pulse.get("regime"),
                horizon=Horizon.NOWCAST,
                direction=direction,
                confidence=_clamp01(float(pulse.get("confidence", 0.0)) / 100.0),
                expected_move=str(score),
                expected_move_unit=MoveUnit.SCORE,
                ttl_seconds=ttl_seconds,
                data_quality=quality(
                    source_at, fetched_at, ttl_seconds, completeness=max(0.0, min(1.0, coverage))
                ),
            )
        ]


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))
