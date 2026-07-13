"""Track-record scorer + confidence calibration — pure functions, no I/O.

Scoring model (KRW view, matching the platform's won-centric cash framing):
- every USD-quoted proxy return is converted to KRW via the USDKRW leg, so
  "달러 보유" earns exactly the USDKRW move and US assets earn asset+FX;
- portfolio return = Σ weight × KRW-view return (CASH = 0 by definition);
- skill = portfolio return − neutral-baseline return (allocation excess);
- direction hit = sign(risk_on) vs sign(risky basket − defensive basket),
  scored only when a directional call was actually made (|risk_on| ≥ 0.05).

Calibration: once ≥ MIN_SCORED directional outcomes exist, displayed confidence
is nudged toward the realized hit rate — bounded (±0.15) and clamped, so the
loop can correct persistent over/under-confidence but can never fabricate
certainty. Mirrors the KOSPI watcher's confidence_target approach.
"""

from __future__ import annotations

from autopilot.domain.track.schemas import TrackPrediction, TrackScore, TrackSummary

RISKY = ("US_EQUITY", "KOREA_EQUITY", "BITCOIN")
DEFENSIVE = ("US_TREASURY", "GOLD", "USD", "CASH")
_USD_QUOTED = ("US_TREASURY", "US_EQUITY", "BITCOIN", "GOLD")

NEUTRAL_BAND = 0.05  # |risk_on| below this = "no directional call" -> not graded
MIN_SCORED = 20  # directional outcomes required before calibration activates
MAX_ADJUST = 0.15  # calibration can never move confidence more than this


def _future_return(
    series: list[tuple[str, float]], after_date: str, horizon_days: int
) -> float | None:
    """Close-to-close return over `horizon_days` sessions starting from the first
    session strictly after `after_date`. None while not enough future data exists."""
    idx = next((i for i, (d, _c) in enumerate(series) if d > after_date), None)
    if idx is None or idx + horizon_days >= len(series):
        return None
    entry, exit_ = series[idx][1], series[idx + horizon_days][1]
    if entry <= 0:
        return None
    return exit_ / entry - 1.0


def _krw_returns(
    prices: dict[str, list[tuple[str, float]]], after_date: str, horizon_days: int
) -> dict[str, float] | None:
    """KRW-view horizon return per asset. None unless ALL assets are scoreable
    (partial scoring would silently bias the portfolio-vs-neutral comparison)."""
    fx = _future_return(prices.get("USD", []), after_date, horizon_days)
    if fx is None:
        return None
    out: dict[str, float] = {"USD": fx, "CASH": 0.0}
    for asset in ("US_TREASURY", "US_EQUITY", "KOREA_EQUITY", "BITCOIN", "GOLD"):
        r = _future_return(prices.get(asset, []), after_date, horizon_days)
        if r is None:
            return None
        out[asset] = (1.0 + r) * (1.0 + fx) - 1.0 if asset in _USD_QUOTED else r
    return out


def _basket(returns: dict[str, float], assets: tuple[str, ...]) -> float:
    vals = [returns[a] for a in assets if a in returns]
    return sum(vals) / len(vals) if vals else 0.0


def score_predictions(
    predictions: list[TrackPrediction],
    prices: dict[str, list[tuple[str, float]]],
    *,
    horizon_days: int = 5,
    min_coverage: float = 0.5,
) -> tuple[list[TrackScore], TrackSummary]:
    scores: list[TrackScore] = []
    for p in sorted(predictions, key=lambda x: x.date):
        if p.coverage < min_coverage:
            continue  # a 1-of-4-watcher day is not a representative call
        returns = _krw_returns(prices, p.date, horizon_days)
        if returns is None:
            continue  # pending — not enough future sessions yet
        port = sum(w * returns.get(a, 0.0) for a, w in p.weights.items())
        neutral = sum(w * returns.get(a, 0.0) for a, w in p.neutral.items())
        spread = _basket(returns, RISKY) - _basket(returns, DEFENSIVE)
        hit: bool | None = None
        if abs(p.risk_on) >= NEUTRAL_BAND and abs(spread) > 1e-12:
            hit = (p.risk_on > 0) == (spread > 0)
        scores.append(
            TrackScore(
                date=p.date,
                regime=p.regime,
                risk_on=p.risk_on,
                confidence=p.confidence,
                portfolio_return_pct=round(port * 100, 3),
                neutral_return_pct=round(neutral * 100, 3),
                excess_pct=round((port - neutral) * 100, 3),
                risk_spread_pct=round(spread * 100, 3),
                hit=hit,
            )
        )

    directional = [s for s in scores if s.hit is not None]
    cum = 1.0
    for s in scores:
        cum *= 1.0 + s.excess_pct / 100.0
    summary = TrackSummary(
        horizon_days=horizon_days,
        n_predictions=len(predictions),
        n_scored=len(scores),
        n_directional=len(directional),
        hit_rate=(
            round(sum(1 for s in directional if s.hit) / len(directional), 4)
            if directional
            else None
        ),
        avg_stated_confidence=(
            round(sum(s.confidence for s in scores) / len(scores), 4) if scores else None
        ),
        avg_excess_pct=(
            round(sum(s.excess_pct for s in scores) / len(scores), 3) if scores else None
        ),
        cum_excess_pct=round((cum - 1.0) * 100, 3) if scores else None,
    )
    return scores, summary


def calibrate_confidence(
    confidence: float,
    *,
    hit_rate: float | None,
    avg_stated_confidence: float | None,
    n_directional: int,
) -> float:
    """Bounded feedback: move displayed confidence toward the realized hit rate.

    No-op until MIN_SCORED directional outcomes exist. The correction is half the
    (realized − stated) gap, clamped to ±MAX_ADJUST and to [0.05, 0.95] — it can
    fix persistent miscalibration but can never manufacture certainty."""
    if (
        n_directional < MIN_SCORED
        or hit_rate is None
        or avg_stated_confidence is None
    ):
        return confidence
    adjust = max(-MAX_ADJUST, min(MAX_ADJUST, 0.5 * (hit_rate - avg_stated_confidence)))
    return max(0.05, min(0.95, confidence + adjust))
