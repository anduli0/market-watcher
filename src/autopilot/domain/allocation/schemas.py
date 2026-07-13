"""Cross-asset optimal-portfolio contract (MARKET WATCHER centerpiece).

A single deterministic view of how to position across 달러 / 미국채 / 미장 / 국장 /
현금 / 비트코인 / 금 given the unified regime, the watchers' forward signals, and news.
Analytical output only — not an order.
"""

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from autopilot.domain.enums import AssetClass, Regime
from autopilot.domain.signals.schemas import InvalidationCondition


class AssetAllocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    asset: AssetClass
    label_ko: str
    weight: float = Field(ge=0.0, le=1.0)
    neutral_weight: float = Field(ge=0.0, le=1.0)
    stance: str  # OVERWEIGHT | NEUTRAL | UNDERWEIGHT
    score: float
    rationale: str
    drivers: tuple[str, ...] = ()


class CrossAssetPortfolio(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    as_of: AwareDatetime
    regime_id: str
    primary_regime: Regime
    risk_on_score: float = Field(ge=-1.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    coverage: float = Field(ge=0.0, le=1.0)
    headline: str
    allocations: tuple[AssetAllocation, ...]
    notes: tuple[str, ...] = ()
    invalidation_conditions: tuple[InvalidationCondition, ...] = ()

    @property
    def weights(self) -> dict[str, float]:
        return {a.asset.value: a.weight for a in self.allocations}
