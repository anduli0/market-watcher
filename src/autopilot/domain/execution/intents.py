"""Turn Meta-CIO target exposures into broker-independent TradeIntents via the
Instrument Translator. Pure. A TradeIntent carries no authority — it must still pass
the Risk Engine. Exposures with no approved instrument produce no intent (recorded).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from autopilot.domain.cio.schemas import CioDecision
from autopilot.domain.enums import Book, ExposureDirection, OrderSide
from autopilot.domain.execution.schemas import TradeIntent
from autopilot.domain.instruments.registry import InstrumentRegistry
from autopilot.domain.instruments.translator import TranslationResult, translate

_STRATEGY = "weekly-macro-allocation"


@dataclass(frozen=True)
class IntentProposal:
    exposure: str
    direction: ExposureDirection
    translation: TranslationResult
    intent: TradeIntent | None


def build_proposals(
    cio: CioDecision,
    registry: InstrumentRegistry,
    *,
    allowed_instruments: set[str],
    as_of: datetime,
    signal_ttl_seconds: int = 3600,
) -> list[IntentProposal]:
    proposals: list[IntentProposal] = []
    for target in cio.targets:
        if target.direction is ExposureDirection.FLAT:
            continue
        tr = translate(target.exposure, registry, allowed_instruments=allowed_instruments)
        intent: TradeIntent | None = None
        if tr.chosen is not None:
            book = tr.chosen.allowed_books[0] if tr.chosen.allowed_books else Book.STRATEGIC_REGIME
            side = (
                OrderSide.BUY if target.direction is ExposureDirection.INCREASE else OrderSide.SELL
            )
            key = f"{cio.cio_decision_id}:{target.exposure}:{side.value}"
            intent = TradeIntent(
                intent_id=key,
                created_at=as_of,
                strategy=_STRATEGY,
                book=book,
                economic_exposure=target.exposure,
                instrument_id=tr.chosen.ticker,
                side=side,
                target_weight_change=str(target.target_weight_change),
                requested_quantity=1,  # placeholder until live quote enables sizing
                reference_price=None,
                signal_expiry=as_of + timedelta(seconds=signal_ttl_seconds),
                thesis_id=cio.cio_decision_id,
                idempotency_key=key,
                risk_context={"target_weight_change": float(target.target_weight_change)},
            )
        proposals.append(IntentProposal(target.exposure, target.direction, tr, intent))
    return proposals
