"""The Market Regime Engine — deterministic fusion of the four watchers' normalized
signals into a unified macro regime (build spec §5.3).

Pure function, no I/O, no LLM. Given the same signals + config it returns the same
assessment. It produces a primary/secondary regime, a probability distribution,
confidence, coverage, supporting/contradictory signals, transition risk, and
invalidation conditions. Yield decomposition is filled only when macro series are
supplied (not fabricated).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from autopilot.domain.enums import (
    ComparisonOperator,
    Regime,
    SignalDirection,
    Watcher,
)
from autopilot.domain.regime.schemas import RegimeAssessment, YieldDecomposition
from autopilot.domain.signals.schemas import InvalidationCondition, NormalizedSignal

_NS = uuid.UUID("a1f0c0de-0000-4000-8000-0bad0bad0bad")

# Which group each target belongs to (for feature aggregation & supporting/contra).
_FED_TARGETS = {"US_POLICY_RATE_PATH"}
_USD_TARGETS = {"USD_KRW"}
_US_EQUITY_TARGETS = {"US_EQUITY"}
_KR_EQUITY_TARGETS = {"KOSPI200"}

# Fed horizon weights — near-term stance dominates the "current regime".
_FED_HORIZON_WEIGHT = {"6M": 1.0, "12M": 1.0, "3Y": 0.5, "10Y": 0.3}

# FX (USD/KRW) horizon weights — the KRW watcher publishes 1W..12M; the current
# regime is driven by the near horizons, the 12M view only tempers it.
_FX_HORIZON_WEIGHT = {"1W": 1.0, "D5": 1.0, "1M": 1.0, "3M": 0.7, "12M": 0.4}

# Equity horizon weights — the CIO acts on a ~1M horizon, so D20/1M signals count
# fully and very short/very long horizons are tempered (not dropped).
_EQ_HORIZON_WEIGHT = {
    "INTRADAY": 0.6,
    "NOWCAST": 0.8,
    "D5": 0.9,
    "1W": 0.9,
    "D20": 1.0,
    "1M": 1.0,
    "D60": 0.8,
    "3M": 0.7,
}

# Native-regime -> risk-off intensity [0,1].
_US_RISK_OFF = {
    "BEAR_MARKET": 1.0,
    "RISK_OFF": 0.9,
    "CORRECTION": 0.6,
    "TRANSITION_WATCH": 0.4,
    "OVERHEATED_RALLY": 0.2,
}
_KOSPI_RISK_OFF = {
    "CRISIS": 1.0,
    "RISK_OFF": 0.85,
    "SIDEWAYS_HIGH_VOL": 0.45,
    "DATA_UNCERTAIN": 0.3,
    "RISK_ON_FRAGILE": 0.2,
}


@dataclass(frozen=True)
class RegimeFeatures:
    fed_stance: float  # +hawkish .. -dovish
    us_equity: float  # +up .. -down
    kospi_equity: float
    usd_strength: float  # +USD strong (KRW weak)
    risk_off: float  # 0..1
    coverage: float  # 0..1 over the four watchers
    avg_quality: float  # 0..1
    agreement: float  # 0..1
    groups_present: frozenset[str]

    @property
    def equity(self) -> float:
        present = [
            v
            for v, g in ((self.us_equity, "US_EQUITY"), (self.kospi_equity, "KR_EQUITY"))
            if g in self.groups_present
        ]
        return sum(present) / len(present) if present else 0.0

    @property
    def divergence_kr_us(self) -> float:
        if {"US_EQUITY", "KR_EQUITY"} <= self.groups_present:
            return abs(self.us_equity - self.kospi_equity)
        return 0.0


def _dv(sig: NormalizedSignal) -> float:
    return {SignalDirection.UP: 1.0, SignalDirection.DOWN: -1.0}.get(sig.direction, 0.0)


def _weighted(
    signals: list[NormalizedSignal], horizon_weight: dict[str, float] | None = None
) -> float:
    num = den = 0.0
    for s in signals:
        w = s.confidence * s.data_quality.overall
        if horizon_weight is not None:
            w *= horizon_weight.get(s.horizon.value, 0.5)
        num += _dv(s) * w
        den += w
    return num / den if den > 0 else 0.0


def extract_features(signals: list[NormalizedSignal]) -> RegimeFeatures:
    by_group: dict[str, list[NormalizedSignal]] = {
        "FED": [],
        "USD": [],
        "US_EQUITY": [],
        "KR_EQUITY": [],
    }
    for s in signals:
        if s.target in _FED_TARGETS:
            by_group["FED"].append(s)
        elif s.target in _USD_TARGETS:
            by_group["USD"].append(s)
        elif s.target in _US_EQUITY_TARGETS:
            by_group["US_EQUITY"].append(s)
        elif s.target in _KR_EQUITY_TARGETS:
            by_group["KR_EQUITY"].append(s)

    present = frozenset(g for g, v in by_group.items() if v)
    fed = _weighted(by_group["FED"], _FED_HORIZON_WEIGHT)
    usd = _weighted(by_group["USD"], _FX_HORIZON_WEIGHT)
    us_eq = _weighted(by_group["US_EQUITY"], _EQ_HORIZON_WEIGHT)
    kr_eq = _weighted(by_group["KR_EQUITY"], _EQ_HORIZON_WEIGHT)

    risk_off = 0.0
    for s in signals:
        if not s.regime:
            continue
        if s.watcher is Watcher.US_WATCHER:
            risk_off = max(risk_off, _US_RISK_OFF.get(s.regime, 0.0))
        elif s.watcher is Watcher.KOSPI_WATCHER:
            risk_off = max(risk_off, _KOSPI_RISK_OFF.get(s.regime, 0.0))

    coverage = len(present) / 4.0
    qualities = [s.data_quality.overall for s in signals]
    avg_quality = sum(qualities) / len(qualities) if qualities else 0.0
    if {"US_EQUITY", "KR_EQUITY"} <= present:
        agreement = 1.0 - abs(us_eq - kr_eq) / 2.0
    elif present & {"US_EQUITY", "KR_EQUITY"}:
        agreement = 0.6
    else:
        agreement = 0.5

    return RegimeFeatures(
        fed_stance=fed,
        us_equity=us_eq,
        kospi_equity=kr_eq,
        usd_strength=usd,
        risk_off=risk_off,
        coverage=coverage,
        avg_quality=avg_quality,
        agreement=agreement,
        groups_present=present,
    )


def _pos(x: float) -> float:
    return max(0.0, x)


def _neg(x: float) -> float:
    return max(0.0, -x)


def score_regimes(f: RegimeFeatures) -> dict[Regime, float]:
    eq, hawk, dov = f.equity, _pos(f.fed_stance), _neg(f.fed_stance)
    R = Regime
    raw: dict[Regime, float] = {
        R.GOLDILOCKS: _pos(eq) * (1.0 - hawk) * (1.0 - f.risk_off),
        R.HAWKISH_GROWTH: hawk * _pos(eq) * (1.0 - f.risk_off),
        R.HAWKISH_SLOWDOWN: hawk * _neg(eq),
        R.POLICY_EASING_TRANSITION: dov * (_pos(eq) + 0.3 * (1.0 - abs(eq))) * (1.0 - f.risk_off),
        R.RECESSION_RISK: f.risk_off * (0.5 + 0.5 * _neg(eq)),
        # macro-limited (need breakevens/real yields) -> damped, never dominant alone
        R.STAGFLATION: hawk * _neg(eq) * _pos(f.usd_strength) * 0.6,
        R.REINFLATION: hawk * _pos(eq) * 0.3,
        R.LIQUIDITY_STRESS: f.risk_off * _pos(f.usd_strength) * 0.7,
        R.USD_STRENGTH: _pos(f.usd_strength) * (0.6 + 0.4 * (1.0 - abs(eq))),
        R.KRW_STRENGTH: _neg(f.usd_strength),
        R.KOREA_DECOUPLING: f.divergence_kr_us / 2.0,
        R.US_TECH_LEADERSHIP: _pos(f.us_equity) * (0.5 + 0.5 * _pos(f.us_equity - f.kospi_equity)),
        R.DEFENSIVE_ROTATION: f.risk_off * 0.4 * (1.0 - _pos(eq)),
        # need style/sector rotation data (US /rotation) -> tiny base only
        R.VALUE_ROTATION: 0.0,
    }
    raw[R.REGIME_UNCERTAIN] = (
        0.40 * (1.0 - f.coverage) + 0.30 * (1.0 - f.agreement) + 0.30 * (1.0 - f.avg_quality) + 0.10
    )
    return {k: max(0.0, v) for k, v in raw.items()}


def _normalize(raw: dict[Regime, float]) -> dict[Regime, float]:
    total = sum(raw.values())
    if total <= 0:
        return {Regime.REGIME_UNCERTAIN: 1.0}
    return {k: v / total for k, v in raw.items() if v > 0}


# Expected directional signature per regime: group -> expected sign (+1/-1).
_SIGNATURE: dict[Regime, dict[str, int]] = {
    Regime.GOLDILOCKS: {"EQUITY": 1, "FED": -1},
    Regime.HAWKISH_GROWTH: {"EQUITY": 1, "FED": 1},
    Regime.HAWKISH_SLOWDOWN: {"EQUITY": -1, "FED": 1},
    Regime.POLICY_EASING_TRANSITION: {"EQUITY": 1, "FED": -1},
    Regime.RECESSION_RISK: {"EQUITY": -1},
    Regime.STAGFLATION: {"EQUITY": -1, "FED": 1, "USD": 1},
    Regime.REINFLATION: {"EQUITY": 1, "FED": 1},
    Regime.LIQUIDITY_STRESS: {"EQUITY": -1, "USD": 1},
    Regime.USD_STRENGTH: {"USD": 1},
    Regime.KRW_STRENGTH: {"USD": -1},
    Regime.US_TECH_LEADERSHIP: {"EQUITY": 1},
    Regime.DEFENSIVE_ROTATION: {"EQUITY": -1},
}

_TARGET_GROUP = {
    "US_POLICY_RATE_PATH": "FED",
    "USD_KRW": "USD",
    "US_EQUITY": "EQUITY",
    "KOSPI200": "EQUITY",
}


def _support_split(
    primary: Regime, signals: list[NormalizedSignal]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    sig = _SIGNATURE.get(primary, {})
    supporting: list[str] = []
    contradictory: list[str] = []
    for s in signals:
        group = _TARGET_GROUP.get(s.target)
        expected = sig.get(group) if group else None
        if expected is None:
            continue
        d = _dv(s)
        if d == 0:
            continue
        if (d > 0) == (expected > 0):
            supporting.append(s.signal_id)
        else:
            contradictory.append(s.signal_id)
    return tuple(supporting), tuple(contradictory)


def _invalidations(primary: Regime) -> tuple[InvalidationCondition, ...]:
    sig = _SIGNATURE.get(primary, {})
    metric = {"FED": "FED_STANCE", "EQUITY": "EQUITY_TILT", "USD": "USD_STRENGTH"}
    conds: list[InvalidationCondition] = []
    for group, expected in sig.items():
        op = ComparisonOperator.LT if expected > 0 else ComparisonOperator.GT
        conds.append(InvalidationCondition(metric=metric[group], operator=op, value="0"))
    return tuple(conds)


def assess_regime(
    signals: list[NormalizedSignal],
    *,
    as_of: datetime,
    prior_regime: Regime | None = None,
    macro: YieldDecomposition | None = None,
) -> RegimeAssessment:
    f = extract_features(signals)
    probs = _normalize(score_regimes(f))
    ranked = sorted(probs.items(), key=lambda kv: (-kv[1], kv[0].value))
    primary, p1 = ranked[0]
    secondary, p2 = ranked[1] if len(ranked) > 1 else (None, 0.0)

    # Decision confidence: how clearly the top regime leads (margin), scaled by data
    # coverage, quality, and signal agreement. (Raw top-probability mass understates
    # confidence because it is diluted across many candidate regimes.)
    margin = p1 - p2
    m_score = min(1.0, margin / 0.20)
    confidence = max(
        0.0,
        min(
            0.95,
            (0.40 + 0.45 * m_score)
            * (0.55 + 0.45 * f.coverage)
            * (0.65 + 0.35 * f.avg_quality)
            * (0.75 + 0.25 * f.agreement),
        ),
    )
    # Transition risk uses the SAME margin scale as confidence (margin/0.20 saturates):
    # with 15 candidate regimes the raw normalized margin is structurally small, so the
    # unscaled version sat chronically at 0.5+ regardless of how clear the call was.
    transition_risk = max(0.0, min(1.0, 0.5 * (1.0 - m_score) + 0.5 * (1.0 - f.agreement)))
    supporting, contradictory = _support_split(primary, signals)

    all_ids = "|".join(sorted(s.signal_id for s in signals))
    regime_id = uuid.uuid5(_NS, f"regime|{as_of.isoformat()}|{primary.value}|{all_ids}").hex

    return RegimeAssessment(
        regime_id=regime_id,
        as_of=as_of,
        primary_regime=primary,
        secondary_regime=secondary,
        regime_probabilities={k.value: round(v, 4) for k, v in probs.items()},
        confidence=max(0.0, min(1.0, confidence)),
        coverage=f.coverage,
        supporting_signals=supporting,
        contradictory_signals=contradictory,
        prior_regime=prior_regime,
        regime_changed=prior_regime is not None and prior_regime != primary,
        transition_risk=transition_risk,
        invalidation_conditions=_invalidations(primary),
        yield_decomposition=macro or YieldDecomposition(),
    )
