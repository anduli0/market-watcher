"""Instrument Translator (build spec §5.6): economic exposure -> approved Kiwoom-
tradable instrument. Never invents a ticker; only selects from the registry, and only
marks an instrument tradable when it is active AND allow-listed AND (when metrics
exist) liquid enough. Deny-by-default: empty allow-list => nothing is tradable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from autopilot.domain.enums import Book
from autopilot.domain.instruments.registry import InstrumentRegistry
from autopilot.domain.instruments.schemas import Instrument


@dataclass(frozen=True)
class TranslationResult:
    exposure: str
    chosen: Instrument | None
    candidates: tuple[Instrument, ...]
    tradable: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)


def _rank_key(i: Instrument, allow: set[str]) -> tuple[int, int, float]:
    # prefer allow-listed, then active, then cheaper (lower expense ratio).
    return (
        0 if i.ticker in allow else 1,
        0 if i.active else 1,
        float(i.expense_ratio_bps if i.expense_ratio_bps is not None else 9999),
    )


def translate(
    exposure: str,
    registry: InstrumentRegistry,
    *,
    allowed_instruments: set[str],
    book: Book | None = None,
    min_liquidity: float | None = None,
) -> TranslationResult:
    candidates = registry.for_exposure(exposure)
    if book is not None:
        candidates = [i for i in candidates if book in i.allowed_books]
    if not candidates:
        return TranslationResult(
            exposure,
            None,
            (),
            False,
            (f"no registered instrument for exposure {exposure}",),
        )

    ranked = sorted(candidates, key=lambda i: _rank_key(i, allowed_instruments))
    chosen = ranked[0]
    reasons: list[str] = []
    tradable = True

    if chosen.ticker not in allowed_instruments:
        tradable = False
        reasons.append(f"{chosen.ticker} not in risk allow-list (deny-by-default)")
    if not chosen.active:
        tradable = False
        reasons.append(f"{chosen.ticker} inactive in registry")
    liq = chosen.metrics.liquidity_score
    if liq is None:
        tradable = False
        reasons.append(f"{chosen.ticker} liquidity metrics not yet populated")
    elif min_liquidity is not None and liq < min_liquidity:
        tradable = False
        reasons.append(f"{chosen.ticker} liquidity {liq:.2f} < min {min_liquidity:.2f}")
    if (chosen.inverse or chosen.leveraged) and book is not Book.HEDGE:
        tradable = False
        reasons.append(f"{chosen.ticker} leveraged/inverse — Hedge-Book whitelist only")

    if tradable:
        reasons.append(f"{chosen.ticker} approved candidate for {exposure}")
    return TranslationResult(exposure, chosen, tuple(ranked), tradable, tuple(reasons))
