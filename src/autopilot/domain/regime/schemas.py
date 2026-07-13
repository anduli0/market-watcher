"""Market Regime Engine output contract (DATA_CONTRACTS.md §3).

Deterministic: identical normalized inputs + config -> identical assessment.
Produces NO broker order — it is an analytical conclusion only.
"""

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from autopilot.domain.enums import Regime
from autopilot.domain.signals.schemas import InvalidationCondition


class YieldDecomposition(BaseModel):
    """Decomposition of the yield/rate move into drivers. Populated only when a
    macro-series snapshot (Fed /api/macro/series: GS10, DFII10, T10YIE, T10Y2Y, ...)
    is supplied. Until that adapter is wired it is honestly marked unavailable —
    never fabricated."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    available: bool = False
    basis: str = "macro series not ingested (Fed /api/macro/series pending)"
    nominal_change_bps: float | None = None
    real_change_bps: float | None = None
    inflation_expectation_change_bps: float | None = None
    term_premium_change_bps: float | None = None
    growth_driven: float | None = None
    inflation_driven: float | None = None
    fiscal_driven: float | None = None


class RegimeAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    regime_id: str
    as_of: AwareDatetime
    primary_regime: Regime
    secondary_regime: Regime | None
    regime_probabilities: dict[str, float]
    confidence: float = Field(ge=0.0, le=1.0)
    coverage: float = Field(ge=0.0, le=1.0)
    supporting_signals: tuple[str, ...] = ()
    contradictory_signals: tuple[str, ...] = ()
    prior_regime: Regime | None = None
    regime_changed: bool = False
    transition_risk: float = Field(ge=0.0, le=1.0)
    invalidation_conditions: tuple[InvalidationCondition, ...] = ()
    yield_decomposition: YieldDecomposition = Field(default_factory=YieldDecomposition)
