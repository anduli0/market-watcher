"""FED WATCHER adapter. Source: GET /api/forecast/horizons (public).

The Fed forecast is the cumulative bps change in the US policy-rate path from the
current DFF, per horizon (6m/12m/3y/10y), quantized to 25bps. `signal` is the
hawkish/neutral/dovish label. Timestamps are serialized NAIVE and are documented to
be UTC (see REPOSITORY_AUDIT §3), so we attach UTC explicitly.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from autopilot.adapters.base import WatcherAdapter, make_signal_id, quality
from autopilot.domain.enums import (
    ComparisonOperator,
    Horizon,
    MoveUnit,
    SignalDirection,
    Watcher,
)
from autopilot.domain.signals.schemas import InvalidationCondition, NormalizedSignal
from autopilot.domain.time import parse_iso_utc

_HORIZON = {"6m": Horizon.M6, "12m": Horizon.M12, "3y": Horizon.Y3, "10y": Horizon.Y10}
_DIRECTION = {
    "hawkish": SignalDirection.UP,
    "dovish": SignalDirection.DOWN,
    "neutral": SignalDirection.NEUTRAL,
}
_TARGET = "US_POLICY_RATE_PATH"


class FedWatcherAdapter(WatcherAdapter):
    watcher = Watcher.FED_WATCHER

    @property
    def latest_path(self) -> str:
        return "/api/forecast/horizons"

    @property
    def health_path(self) -> str:
        return "/health"

    @classmethod
    def parse(cls, body: Any, fetched_at: datetime, ttl_seconds: int) -> list[NormalizedSignal]:
        if not isinstance(body, dict):
            raise ValueError("expected an object keyed by horizon")
        signals: list[NormalizedSignal] = []
        for key, h in _HORIZON.items():
            row = body.get(key)
            if row is None:
                continue  # a missing horizon is not fatal — fewer signals, not bad ones
            signal_label = row["signal"]
            direction = _DIRECTION.get(signal_label, SignalDirection.NEUTRAL)
            published_at = row.get("published_at")
            if published_at:
                source_at = parse_iso_utc(published_at, naive_is_utc=True)
                source_health = 1.0
            else:
                source_at = fetched_at
                source_health = 0.6  # no publish time -> freshness unverifiable
            invalidations = cls._bands(row)
            signals.append(
                NormalizedSignal(
                    signal_id=make_signal_id(cls.watcher, _TARGET, h.value, source_at),
                    watcher=cls.watcher,
                    generated_at=fetched_at,
                    source_data_at=source_at,
                    model_version="fed-v0",
                    target=_TARGET,
                    regime=signal_label,
                    horizon=h,
                    direction=direction,
                    confidence=_clamp01(row.get("confidence", 0.0)),
                    expected_move=str(row["published_delta_bps"]),
                    expected_move_unit=MoveUnit.BPS,
                    drivers=((row["trigger_event"],) if row.get("trigger_event") else ()),
                    invalidation_conditions=invalidations,
                    ttl_seconds=ttl_seconds,
                    data_quality=quality(
                        source_at, fetched_at, ttl_seconds, source_health=source_health
                    ),
                )
            )
        if not signals:
            raise ValueError("no recognizable horizons in body")
        return signals

    @staticmethod
    def _bands(row: dict[str, Any]) -> tuple[InvalidationCondition, ...]:
        low, high = row.get("band_low_bps"), row.get("band_high_bps")
        conds: list[InvalidationCondition] = []
        if low is not None:
            conds.append(
                InvalidationCondition(
                    metric="US_POLICY_RATE_DELTA_BPS",
                    operator=ComparisonOperator.LT,
                    value=str(low),
                )
            )
        if high is not None:
            conds.append(
                InvalidationCondition(
                    metric="US_POLICY_RATE_DELTA_BPS",
                    operator=ComparisonOperator.GT,
                    value=str(high),
                )
            )
        return tuple(conds)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))
