"""Execution-domain contracts: TradeIntent, RiskLimits, RiskContext, RiskCheckResult,
RiskDecision, KillSwitchState. A TradeIntent is NOT an order — it becomes one only
after an APPROVED RiskDecision (build spec §5.7/§5.8).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from autopilot.domain.enums import (
    AppMode,
    Book,
    OrderSide,
    OrderType,
    RiskCheckCode,
    RiskDecisionStatus,
)
from autopilot.domain.money import DecimalNoFloat


class TradeIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    intent_id: str
    created_at: AwareDatetime
    strategy: str
    book: Book
    economic_exposure: str
    instrument_id: str  # approved-registry ticker
    side: OrderSide
    target_weight_change: DecimalNoFloat
    requested_quantity: int = Field(gt=0)
    preferred_order_type: OrderType = OrderType.LIMIT
    reference_price: DecimalNoFloat | None = None
    maximum_slippage_bps: int = 20
    signal_expiry: AwareDatetime
    thesis_id: str | None = None
    idempotency_key: str = Field(min_length=1)
    risk_context: dict[str, float] = Field(default_factory=dict)


class RiskLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = 1
    allowed_instruments: frozenset[str] = frozenset()
    allowed_strategies: frozenset[str] = frozenset()
    market_open: bool = False
    max_order_notional: DecimalNoFloat = Decimal("0")
    max_order_quantity: int = 0
    price_deviation_pct: DecimalNoFloat = Decimal("0")
    signal_max_age_seconds: int = 3600
    daily_trade_count: int = 0
    max_open_orders: int = 0
    max_single_instrument_weight_pct: DecimalNoFloat = Decimal("0")
    daily_loss_limit: DecimalNoFloat = Decimal("0")
    max_gross_exposure: DecimalNoFloat = Decimal("0")


@dataclass(frozen=True)
class RiskContext:
    as_of: datetime
    app_mode: AppMode = AppMode.READ_ONLY
    kill_switch_engaged: bool = False
    market_open: bool | None = None
    last_price: Decimal | None = None
    position_notional: Decimal = Decimal("0")
    gross_exposure: Decimal = Decimal("0")
    daily_realized_loss: Decimal = Decimal("0")
    open_orders: int = 0
    daily_trade_count: int = 0
    watcher_fresh: bool = True
    seen_idempotency_keys: frozenset[str] = field(default_factory=frozenset)


class RiskCheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: RiskCheckCode
    passed: bool
    detail: str


class RiskDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_id: str
    intent_id: str
    status: RiskDecisionStatus
    created_at: AwareDatetime
    checks: tuple[RiskCheckResult, ...] = ()
    failed_checks: tuple[RiskCheckCode, ...] = ()
    approved_quantity: int = 0
    reason: str = ""
    requires_human: bool = False

    @property
    def approved(self) -> bool:
        return self.status in (
            RiskDecisionStatus.APPROVED,
            RiskDecisionStatus.APPROVED_WITH_REDUCED_SIZE,
        )


class KillSwitchState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    engaged: bool = False
    reason: str | None = None
    source: str | None = None
    since: AwareDatetime | None = None
