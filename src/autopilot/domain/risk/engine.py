"""Deterministic, deny-by-default Risk Engine (build spec §5.7).

No LLM, no I/O, no broker — pure rules over a TradeIntent + RiskContext + RiskLimits.
Checks that need live infrastructure not yet wired return a clearly labelled
[PLACEHOLDER] pass and MUST be implemented before any LIVE mode; they never gate-open a
real order because live execution is not implemented. A single failed hard limit
rejects; only sizing breaches can downgrade to APPROVED_WITH_REDUCED_SIZE.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from autopilot.domain.enums import (
    AppMode,
    OrderType,
    RiskCheckCode,
    RiskDecisionStatus,
)
from autopilot.domain.execution.schemas import (
    RiskCheckResult,
    RiskContext,
    RiskDecision,
    RiskLimits,
    TradeIntent,
)
from autopilot.domain.time import now_utc

_PLACEHOLDER = "[PLACEHOLDER] structural check, not evaluated yet; implement before LIVE"

# Checks that are not yet wired to live infrastructure (always pass, clearly labelled).
_PLACEHOLDER_CODES = (
    RiskCheckCode.WEEKLY_LOSS_LIMIT,
    RiskCheckCode.MAX_DRAWDOWN,
    RiskCheckCode.MIN_CASH_RATIO,
    RiskCheckCode.MAX_USD_EXPOSURE,
    RiskCheckCode.MAX_NET_EQUITY_EXPOSURE,
    RiskCheckCode.BOOK_CAPITAL_LIMIT,
    RiskCheckCode.MAX_TURNOVER,
    RiskCheckCode.MAX_CONCURRENT_POSITIONS,
    RiskCheckCode.MAX_UNFILLED_EXPOSURE,
    RiskCheckCode.MAX_SECTOR_WEIGHT,
    RiskCheckCode.MAX_THEMATIC_OVERLAP,
    RiskCheckCode.MAX_FOREIGN_EQUITY_ETF,
    RiskCheckCode.MAX_DURATION,
    RiskCheckCode.MAX_INVERSE_EXPOSURE,
    RiskCheckCode.MAX_LEVERAGED_EXPOSURE,
    RiskCheckCode.MAX_CORRELATION_CLUSTER,
    RiskCheckCode.MAX_PCT_OF_ADV,
    RiskCheckCode.MAX_SPREAD,
    RiskCheckCode.MAX_NAV_PREMIUM_DISCOUNT,
    RiskCheckCode.MAX_SLIPPAGE,
    RiskCheckCode.MIN_LIQUIDITY,
    RiskCheckCode.PENDING_ORDER_CONFLICT,
    RiskCheckCode.KIWOOM_AUTH_HEALTH,
    RiskCheckCode.REST_HEALTH,
    RiskCheckCode.WEBSOCKET_HEALTH,
    RiskCheckCode.REALTIME_DATA_FRESHNESS,
    RiskCheckCode.DB_HEALTH,
    RiskCheckCode.CLOCK_SYNC,
    RiskCheckCode.POSITION_RECONCILIATION,
    RiskCheckCode.PENDING_ORDER_RECONCILIATION,
    RiskCheckCode.DUPLICATE_PROCESS,
)

# Sizing breaches that can downgrade to APPROVED_WITH_REDUCED_SIZE rather than reject.
_SIZABLE = {
    RiskCheckCode.MAX_ORDER_NOTIONAL,
    RiskCheckCode.MAX_ORDER_QUANTITY,
    RiskCheckCode.MAX_GROSS_EXPOSURE,
}


def load_limits(path: str | Path) -> RiskLimits:
    d: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return RiskLimits(
        version=int(d.get("version", 1)),
        allowed_instruments=frozenset(d.get("allowed_instruments") or []),
        allowed_strategies=frozenset(d.get("allowed_strategies") or []),
        market_open=bool(d.get("market_open", False)),
        max_order_notional=str(d.get("max_order_notional", "0")),
        max_order_quantity=int(d.get("max_order_quantity", 0)),
        price_deviation_pct=str(d.get("price_deviation_pct", "0")),
        signal_max_age_seconds=int(d.get("signal_max_age_seconds", 3600)),
        daily_trade_count=int(d.get("daily_trade_count", 0)),
        max_open_orders=int(d.get("max_open_orders", 0)),
        max_single_instrument_weight_pct=str(d.get("max_single_instrument_weight_pct", "0")),
        daily_loss_limit=str(d.get("daily_loss_limit", "0")),
        max_gross_exposure=str(d.get("max_gross_exposure", "0")),
    )


class RiskEngine:
    def __init__(self, limits: RiskLimits) -> None:
        self.limits = limits

    @staticmethod
    def _r(code: RiskCheckCode, passed: bool, detail: str) -> RiskCheckResult:
        return RiskCheckResult(code=code, passed=passed, detail=detail)

    def evaluate(self, intent: TradeIntent, context: RiskContext | None = None) -> RiskDecision:
        ctx = context or RiskContext(as_of=now_utc())
        lim = self.limits
        c: list[RiskCheckResult] = []

        c.append(
            self._r(
                RiskCheckCode.KILL_SWITCH,
                not ctx.kill_switch_engaged,
                "kill switch engaged" if ctx.kill_switch_engaged else "kill switch clear",
            )
        )
        in_allow = intent.instrument_id in lim.allowed_instruments
        c.append(
            self._r(
                RiskCheckCode.INSTRUMENT_ALLOWED,
                in_allow,
                f"{intent.instrument_id} {'in' if in_allow else 'NOT in'} allow-list",
            )
        )
        strat_ok = intent.strategy in lim.allowed_strategies
        c.append(
            self._r(
                RiskCheckCode.STRATEGY_ALLOWED,
                strat_ok,
                f"strategy {intent.strategy} {'allowed' if strat_ok else 'NOT allowed'}",
            )
        )
        market_open = lim.market_open if ctx.market_open is None else ctx.market_open
        c.append(self._r(RiskCheckCode.MARKET_HOURS, market_open, f"market_open={market_open}"))
        c.append(
            self._r(
                RiskCheckCode.WATCHER_DATA_FRESHNESS,
                ctx.watcher_fresh,
                "watcher data fresh" if ctx.watcher_fresh else "watcher data stale/missing",
            )
        )
        not_expired = intent.signal_expiry > ctx.as_of
        c.append(
            self._r(
                RiskCheckCode.STALE_SIGNAL,
                not_expired,
                "intent within signal validity" if not_expired else "signal/intent expired",
            )
        )
        c.append(
            self._r(
                RiskCheckCode.ORDER_TYPE_ALLOWED,
                intent.preferred_order_type is OrderType.LIMIT,
                f"order_type={intent.preferred_order_type.value} (market disabled)",
            )
        )
        is_dup = intent.idempotency_key in ctx.seen_idempotency_keys
        c.append(
            self._r(
                RiskCheckCode.DUPLICATE_ORDER,
                not is_dup,
                "duplicate idempotency_key" if is_dup else "idempotency_key is new",
            )
        )

        # single-instrument target weight
        wt_pct = abs(intent.target_weight_change) * Decimal("100")
        wt_ok = (
            lim.max_single_instrument_weight_pct == 0
            or wt_pct <= lim.max_single_instrument_weight_pct
        )
        c.append(
            self._r(
                RiskCheckCode.MAX_SINGLE_INSTRUMENT_WEIGHT,
                wt_ok,
                f"target weight {wt_pct}% (limit {lim.max_single_instrument_weight_pct}%)",
            )
        )

        # sizing: needs a reference price
        price = intent.reference_price
        approved_qty = intent.requested_quantity
        if price is not None and price > 0:
            notional = Decimal(intent.requested_quantity) * price
            notional_ok = (
                notional <= lim.max_order_notional
                and intent.requested_quantity <= lim.max_order_quantity
            )
            c.append(
                self._r(
                    RiskCheckCode.MAX_ORDER_NOTIONAL,
                    notional_ok,
                    f"notional={notional} qty={intent.requested_quantity} "
                    f"(<= {lim.max_order_notional}, qty<={lim.max_order_quantity})",
                )
            )
            gross_ok = ctx.gross_exposure + notional <= lim.max_gross_exposure
            c.append(
                self._r(
                    RiskCheckCode.MAX_GROSS_EXPOSURE,
                    gross_ok,
                    f"gross+order={ctx.gross_exposure + notional} <= {lim.max_gross_exposure}",
                )
            )
            if not notional_ok and lim.max_order_quantity > 0:
                by_notional = int(lim.max_order_notional / price) if price > 0 else 0
                approved_qty = max(0, min(lim.max_order_quantity, by_notional))
        else:
            c.append(
                self._r(
                    RiskCheckCode.MAX_ORDER_NOTIONAL,
                    False,
                    "cannot size order without a reference price",
                )
            )
            c.append(
                self._r(RiskCheckCode.MAX_GROSS_EXPOSURE, True, "gross check deferred (no price)")
            )
            approved_qty = 0

        c.append(
            self._r(
                RiskCheckCode.DAILY_LOSS_LIMIT,
                ctx.daily_realized_loss <= lim.daily_loss_limit,
                f"daily_loss={ctx.daily_realized_loss} <= {lim.daily_loss_limit}",
            )
        )
        c.append(
            self._r(
                RiskCheckCode.DAILY_TRADE_COUNT,
                ctx.daily_trade_count < lim.daily_trade_count,
                f"trades_today={ctx.daily_trade_count} < {lim.daily_trade_count}",
            )
        )

        for code in _PLACEHOLDER_CODES:
            c.append(self._r(code, True, _PLACEHOLDER))

        failed = tuple(x.code for x in c if not x.passed)
        non_sizable_fail = [f for f in failed if f not in _SIZABLE]
        created = now_utc()

        if not failed:
            status = RiskDecisionStatus.APPROVED
            req_human = ctx.app_mode is AppMode.APPROVAL
            reason = "all implemented risk checks passed"
        elif non_sizable_fail:
            status = RiskDecisionStatus.REJECTED
            approved_qty = 0
            req_human = False
            reason = "rejected by: " + ", ".join(code.value for code in non_sizable_fail)
        elif approved_qty > 0:
            status = RiskDecisionStatus.APPROVED_WITH_REDUCED_SIZE
            req_human = True
            reason = f"sizable breach; reduced to qty={approved_qty}"
        else:
            status = RiskDecisionStatus.REJECTED
            approved_qty = 0
            req_human = False
            reason = "rejected by: " + ", ".join(code.value for code in failed)

        return RiskDecision(
            decision_id=uuid.uuid4().hex,
            intent_id=intent.intent_id,
            status=status,
            created_at=created,
            checks=tuple(c),
            failed_checks=failed,
            approved_quantity=approved_qty if status is not RiskDecisionStatus.REJECTED else 0,
            reason=reason,
            requires_human=req_human,
        )
