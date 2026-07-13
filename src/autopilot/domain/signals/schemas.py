"""The one unified signal contract (DATA_CONTRACTS.md §1). Every WATCHER adapter
produces ``NormalizedSignal``s; nothing downstream depends on watcher-specific JSON.
Immutable (``frozen=True``), versioned, strictly validated.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from autopilot.domain.enums import (
    ComparisonOperator,
    Horizon,
    MoveUnit,
    SignalDirection,
    Watcher,
)
from autopilot.domain.money import DecimalNoFloat

SIGNAL_SCHEMA_VERSION = 1


class DataQuality(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    freshness_score: float = Field(ge=0.0, le=1.0)
    completeness_score: float = Field(ge=0.0, le=1.0)
    source_health_score: float = Field(ge=0.0, le=1.0)

    @property
    def overall(self) -> float:
        """Conservative aggregate — the weakest dimension dominates."""
        return min(self.freshness_score, self.completeness_score, self.source_health_score)


class InvalidationCondition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metric: str
    operator: ComparisonOperator
    value: DecimalNoFloat


class NormalizedSignal(BaseModel):
    """A single normalized signal. ``frozen`` so a stored signal cannot mutate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    signal_id: str
    schema_version: int = SIGNAL_SCHEMA_VERSION
    watcher: Watcher
    generated_at: AwareDatetime
    source_data_at: AwareDatetime
    model_version: str
    target: str
    regime: str | None = None
    horizon: Horizon
    direction: SignalDirection
    probability: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    expected_move: DecimalNoFloat | None = None
    expected_move_unit: MoveUnit | None = None
    drivers: tuple[str, ...] = ()
    counterevidence: tuple[str, ...] = ()
    invalidation_conditions: tuple[InvalidationCondition, ...] = ()
    ttl_seconds: int = Field(gt=0)
    data_quality: DataQuality
    raw_ref: str | None = None

    def data_age_seconds(self, now: datetime) -> float:
        return (now - self.source_data_at).total_seconds()

    def is_stale(self, now: datetime) -> bool:
        """True once the signal has outlived its TTL. Stale signals must be
        excluded by the regime engine — never silently reused."""
        return self.data_age_seconds(now) > self.ttl_seconds
