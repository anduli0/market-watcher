"""KOSPI WATCHER adapter. Source: GET /api/v1/prediction/latest (MarketPrediction).

Korean equity (KOSPI200) direction nowcast over a D5 horizon, with a 9-value regime
label and a OK/PARTIAL/STALE/UNAVAILABLE data-quality flag (mapped to completeness).
`as_of` is aware-UTC.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from autopilot.adapters.base import WatcherAdapter, make_signal_id, quality
from autopilot.domain.enums import Horizon, SignalDirection, Watcher
from autopilot.domain.signals.schemas import NormalizedSignal
from autopilot.domain.time import parse_iso_utc

_DIRECTION = {
    "BULLISH": SignalDirection.UP,
    "BEARISH": SignalDirection.DOWN,
    "NEUTRAL": SignalDirection.NEUTRAL,
}
_HORIZON = {"D5": Horizon.D5, "D20": Horizon.D20, "D60": Horizon.D60}
_COMPLETENESS = {"OK": 1.0, "PARTIAL": 0.7, "STALE": 0.4, "UNAVAILABLE": 0.0}
_TARGET = "KOSPI200"


class KospiWatcherAdapter(WatcherAdapter):
    watcher = Watcher.KOSPI_WATCHER

    @property
    def latest_path(self) -> str:
        return "/api/v1/prediction/latest"

    @property
    def health_path(self) -> str:
        return "/health"

    @classmethod
    def parse(cls, body: Any, fetched_at: datetime, ttl_seconds: int) -> list[NormalizedSignal]:
        if not isinstance(body, dict) or "direction" not in body or "as_of" not in body:
            raise ValueError("expected a MarketPrediction object")
        source_at = parse_iso_utc(body["as_of"])
        horizon = _HORIZON.get(body.get("horizon", "D5"), Horizon.D5)
        completeness = _COMPLETENESS.get(body.get("data_quality", "OK"), 0.7)
        generated_by = body.get("generated_by", "?")
        schema_v = body.get("schema_version", "?")
        return [
            NormalizedSignal(
                signal_id=make_signal_id(cls.watcher, _TARGET, horizon.value, source_at),
                watcher=cls.watcher,
                generated_at=fetched_at,
                source_data_at=source_at,
                model_version=f"kospi-{schema_v}-{generated_by}",
                target=_TARGET,
                regime=body.get("regime"),
                horizon=horizon,
                direction=_DIRECTION.get(body["direction"], SignalDirection.NEUTRAL),
                confidence=_clamp01(body.get("confidence", 0.0)),
                ttl_seconds=ttl_seconds,
                data_quality=quality(source_at, fetched_at, ttl_seconds, completeness=completeness),
            )
        ]


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))
