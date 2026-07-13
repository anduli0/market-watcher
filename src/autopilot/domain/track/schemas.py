"""Track-record contracts: one recorded prediction per KST day, one score per
prediction once enough future sessions exist, and an aggregate summary."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TrackPrediction(BaseModel):
    """What the platform recommended on a given KST date (latest state that day)."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    date: str  # YYYY-MM-DD (KST)
    regime: str
    secondary: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    risk_on: float = Field(ge=-1.0, le=1.0)
    coverage: float = Field(ge=0.0, le=1.0)
    weights: dict[str, float]  # 7-asset recommended weights
    neutral: dict[str, float]  # neutral baseline weights


class TrackScore(BaseModel):
    """Realized outcome of one prediction over the scoring horizon."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    date: str
    regime: str
    risk_on: float
    confidence: float
    portfolio_return_pct: float  # KRW view, recommended weights
    neutral_return_pct: float  # KRW view, neutral weights
    excess_pct: float  # portfolio - neutral (the allocation skill)
    risk_spread_pct: float  # risky basket - defensive basket (realized direction)
    hit: bool | None  # direction call correct; None = no directional call made


class TrackSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    horizon_days: int
    n_predictions: int
    n_scored: int
    n_directional: int
    hit_rate: float | None = None  # over directional calls only
    avg_stated_confidence: float | None = None  # over scored predictions
    avg_excess_pct: float | None = None
    cum_excess_pct: float | None = None
    updated_at: str | None = None
