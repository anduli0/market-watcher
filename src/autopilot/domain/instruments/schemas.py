"""Approved instrument registry schemas (build spec §5.6).

The registry is the CATALOG. An instrument is tradable only if it is BOTH active here
AND allow-listed in risk_limits.yml (deny-by-default). Market-derived metrics may be
null until the InstrumentMetrics service populates them; null metrics fail liquidity
gating, so such an instrument cannot trade.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from autopilot.domain.enums import Book


class InstrumentMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    adv_krw: float | None = None
    avg_spread_bps: float | None = None
    aum_krw: float | None = None
    tracking_error_bps: float | None = None
    liquidity_score: float | None = None


class Instrument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ticker: str
    name_ko: str
    exposure: str
    asset_class: str
    underlying_index: str
    exchange_route: str
    hedged: str  # NA | UNHEDGED | FX_HEDGED
    leveraged: bool
    inverse: bool
    expense_ratio_bps: int | None = None
    duration_years: float | None = None
    allowed_books: tuple[Book, ...] = ()
    max_position_weight: float = Field(ge=0.0, le=1.0)
    active: bool = False
    metrics: InstrumentMetrics = InstrumentMetrics()
