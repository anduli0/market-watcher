"""KRW WATCHER adapter. Source: GET /api/forecast.

USD/KRW per-horizon forecast. `published_delta_krw` is the won move (>0 => USD/KRW up
=> KRW weak). KNOWN LIMITATION: this endpoint exposes NO per-run generation timestamp
(only `target_date`, a date). We therefore cannot verify freshness from this body, so
we anchor `source_data_at` to fetch time and down-weight `source_health_score` (0.6)
so the regime engine treats KRW as freshness-unverified rather than falsely fresh.
TODO(phase-1+): source a precise time from /api/signal.created_at or /health.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from autopilot.adapters.base import WatcherAdapter, make_signal_id, quality
from autopilot.domain.enums import Horizon, MoveUnit, SignalDirection, Watcher
from autopilot.domain.signals.schemas import NormalizedSignal

_HORIZON = {"1w": Horizon.W1, "1m": Horizon.M1, "3m": Horizon.M3, "12m": Horizon.M12}
_DIRECTION = {
    "krw_weak": SignalDirection.UP,  # USD/KRW rises
    "krw_strong": SignalDirection.DOWN,
    "neutral": SignalDirection.NEUTRAL,
}
_TARGET = "USD_KRW"
_SOURCE_HEALTH = 0.6  # no precise generation timestamp on this endpoint


class KrwWatcherAdapter(WatcherAdapter):
    watcher = Watcher.KRW_WATCHER

    @property
    def latest_path(self) -> str:
        return "/api/forecast"

    @property
    def health_path(self) -> str:
        return "/health"

    @classmethod
    def parse(cls, body: Any, fetched_at: datetime, ttl_seconds: int) -> list[NormalizedSignal]:
        if not isinstance(body, dict) or "horizons" not in body:
            raise ValueError("expected an object with a 'horizons' map")
        horizons = body["horizons"]
        if not isinstance(horizons, dict):
            raise ValueError("'horizons' must be an object")
        completeness = len(horizons) / len(_HORIZON) if _HORIZON else 0.0
        signals: list[NormalizedSignal] = []
        for key, h in _HORIZON.items():
            row = horizons.get(key)
            if row is None:
                continue
            label = row["signal"]
            signals.append(
                NormalizedSignal(
                    signal_id=make_signal_id(cls.watcher, _TARGET, h.value, fetched_at),
                    watcher=cls.watcher,
                    generated_at=fetched_at,
                    source_data_at=fetched_at,
                    model_version="krw-v0",
                    target=_TARGET,
                    regime=label,
                    horizon=h,
                    direction=_DIRECTION.get(label, SignalDirection.NEUTRAL),
                    confidence=_clamp01(row.get("confidence", 0.0)),
                    expected_move=str(row["published_delta_krw"]),
                    expected_move_unit=MoveUnit.KRW,
                    ttl_seconds=ttl_seconds,
                    data_quality=quality(
                        fetched_at,
                        fetched_at,
                        ttl_seconds,
                        completeness=min(1.0, completeness),
                        source_health=_SOURCE_HEALTH,
                    ),
                )
            )
        if not signals:
            raise ValueError("no recognizable horizons in body")
        return signals


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))
