"""Meta-CIO output contract (DATA_CONTRACTS.md §4).

The Meta-CIO turns the regime + signals into PORTFOLIO-LEVEL economic exposures and
allocations. It does NOT emit broker-specific order payloads (build spec §5.4).
"""

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from autopilot.domain.enums import ExposureDirection, Horizon, Regime, Watcher
from autopilot.domain.money import DecimalNoFloat
from autopilot.domain.signals.schemas import InvalidationCondition


class WatcherWeight(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    watcher: Watcher
    weight: float = Field(ge=0.0, le=1.0)
    components: dict[str, float]


class TargetExposure(BaseModel):
    """A desired change to an *economic exposure* — never a ticker. The Instrument
    Translator (Phase 3) maps these onto approved Kiwoom-tradable instruments."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    exposure: str
    direction: ExposureDirection
    target_weight_change: DecimalNoFloat
    horizon: Horizon
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str


class CioDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cio_decision_id: str
    as_of: AwareDatetime
    regime_id: str
    primary_regime: Regime
    strategy_brief: str = ""
    risk_on_score: float = Field(ge=-1.0, le=1.0)
    target_cash_ratio: float = Field(ge=0.0, le=1.0)
    asset_class_allocation: dict[str, float]
    country_allocation: dict[str, float]
    style_tilts: dict[str, float]
    sector_tilts: dict[str, float]
    portfolio_confidence: float = Field(ge=0.0, le=1.0)
    disagreements: tuple[str, ...] = ()
    invalidation_conditions: tuple[InvalidationCondition, ...] = ()
    watcher_weights: tuple[WatcherWeight, ...] = ()
    targets: tuple[TargetExposure, ...] = ()
