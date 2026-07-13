"""Meta-CIO engine (build spec §5.4) — deterministic.

Combines the regime assessment + normalized signals into portfolio-level economic
exposures and allocations, with dynamic per-watcher weights. NOT simple majority
voting: weight = accuracy × regime_suitability × horizon_suitability × freshness ×
independence × calibration. Emits NO broker payloads.

Accuracy/calibration use neutral, uniform defaults until Phase 9 attribution supplies
real out-of-sample stats (uniform factors cancel under normalization, so they do not
distort *relative* weighting yet — documented, not hidden).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from autopilot.domain.cio.schemas import CioDecision, TargetExposure, WatcherWeight
from autopilot.domain.enums import ExposureDirection, Horizon, Regime, Watcher, regime_ko
from autopilot.domain.regime.engine import extract_features
from autopilot.domain.regime.schemas import RegimeAssessment
from autopilot.domain.signals.schemas import NormalizedSignal

_NS = uuid.UUID("a1f0c0de-0000-4000-8000-0bad0bad0bad")

_TARGET_WATCHER_GROUP = {
    "US_POLICY_RATE_PATH": Watcher.FED_WATCHER,
    "USD_KRW": Watcher.KRW_WATCHER,
    "US_EQUITY": Watcher.US_WATCHER,
    "KOSPI200": Watcher.KOSPI_WATCHER,
}

# Correlated watcher pairs (shared macro driver) -> independence haircut when both present.
_CORRELATED = [
    (Watcher.FED_WATCHER, Watcher.US_WATCHER),
    (Watcher.KRW_WATCHER, Watcher.KOSPI_WATCHER),
]

# Risk-on base per regime (-1 risk-off .. +1 risk-on).
_RISK_ON: dict[Regime, float] = {
    Regime.GOLDILOCKS: 0.8,
    Regime.HAWKISH_GROWTH: 0.5,
    Regime.US_TECH_LEADERSHIP: 0.6,
    Regime.REINFLATION: 0.2,
    Regime.POLICY_EASING_TRANSITION: 0.4,
    Regime.KRW_STRENGTH: 0.1,
    Regime.VALUE_ROTATION: 0.1,
    Regime.KOREA_DECOUPLING: 0.0,
    Regime.USD_STRENGTH: -0.1,
    Regime.HAWKISH_SLOWDOWN: -0.3,
    Regime.DEFENSIVE_ROTATION: -0.4,
    Regime.STAGFLATION: -0.5,
    Regime.RECESSION_RISK: -0.8,
    Regime.LIQUIDITY_STRESS: -0.9,
    Regime.REGIME_UNCERTAIN: 0.0,
}

# Regime -> exposure playbook: (exposure, base_weight_change). Positive = increase.
_PLAYBOOK: dict[Regime, list[tuple[str, float]]] = {
    Regime.GOLDILOCKS: [
        ("KOREA_LARGE_CAP", 0.05),
        ("US_LARGE_CAP", 0.04),
        ("US_TECH", 0.03),
        ("CASH", -0.06),
        ("US_INTERMEDIATE_TREASURY", -0.02),
    ],
    Regime.HAWKISH_GROWTH: [
        ("US_LARGE_CAP", 0.04),
        ("KOREA_LARGE_CAP", 0.03),
        ("US_SHORT_TREASURY", 0.02),
        ("US_LONG_TREASURY", -0.03),
        ("CASH", -0.02),
    ],
    Regime.US_TECH_LEADERSHIP: [
        ("US_TECH", 0.05),
        ("US_SEMICONDUCTOR", 0.04),
        ("KOREA_SEMICONDUCTOR", 0.03),
        ("CASH", -0.04),
    ],
    Regime.HAWKISH_SLOWDOWN: [
        ("US_TECH", -0.05),
        ("KOREA_LARGE_CAP", -0.03),
        ("US_SHORT_TREASURY", 0.04),
        ("CASH", 0.04),
    ],
    Regime.RECESSION_RISK: [
        ("KOREA_LARGE_CAP", -0.06),
        ("US_LARGE_CAP", -0.05),
        ("US_LONG_TREASURY", 0.05),
        ("US_INTERMEDIATE_TREASURY", 0.04),
        ("CASH", 0.05),
    ],
    Regime.DEFENSIVE_ROTATION: [
        ("KOREA_LARGE_CAP", -0.03),
        ("US_INTERMEDIATE_TREASURY", 0.03),
        ("CASH", 0.04),
    ],
    Regime.STAGFLATION: [
        ("US_TECH", -0.04),
        ("US_SHORT_TREASURY", 0.03),
        ("USD_EXPOSURE", 0.03),
        ("CASH", 0.03),
        ("US_LONG_TREASURY", -0.03),
    ],
    Regime.REINFLATION: [
        ("US_SHORT_TREASURY", 0.02),
        ("KOREA_SEMICONDUCTOR", 0.02),
        ("US_LONG_TREASURY", -0.04),
        ("CASH", -0.02),
    ],
    Regime.POLICY_EASING_TRANSITION: [
        ("US_LONG_TREASURY", 0.05),
        ("US_INTERMEDIATE_TREASURY", 0.03),
        ("KOREA_LARGE_CAP", 0.03),
        ("US_LARGE_CAP", 0.03),
        ("CASH", -0.05),
    ],
    Regime.LIQUIDITY_STRESS: [
        ("CASH", 0.08),
        ("USD_EXPOSURE", 0.04),
        ("KOREA_LARGE_CAP", -0.06),
        ("US_LARGE_CAP", -0.05),
    ],
    Regime.USD_STRENGTH: [
        ("USD_EXPOSURE", 0.05),
        ("US_LARGE_CAP", 0.02),
        ("CASH", 0.01),
        ("KOREA_LARGE_CAP", -0.02),
    ],
    Regime.KRW_STRENGTH: [
        ("USD_EXPOSURE", -0.04),
        ("KOREA_LARGE_CAP", 0.03),
        ("US_LARGE_CAP", -0.02),
    ],
    Regime.KOREA_DECOUPLING: [("CASH", 0.03), ("KOREA_LARGE_CAP", -0.02), ("US_LARGE_CAP", 0.02)],
    Regime.VALUE_ROTATION: [("KOREA_BANKS", 0.03), ("US_TECH", -0.02)],
    Regime.REGIME_UNCERTAIN: [("CASH", 0.05), ("KOREA_LARGE_CAP", -0.02), ("US_LARGE_CAP", -0.02)],
}

# Per-regime watcher relevance buckets for regime_suitability.
_FED_DRIVEN = {
    Regime.HAWKISH_GROWTH,
    Regime.HAWKISH_SLOWDOWN,
    Regime.POLICY_EASING_TRANSITION,
    Regime.STAGFLATION,
    Regime.REINFLATION,
}
_USD_DRIVEN = {Regime.USD_STRENGTH, Regime.KRW_STRENGTH}
_EQUITY_DRIVEN = {
    Regime.GOLDILOCKS,
    Regime.US_TECH_LEADERSHIP,
    Regime.RECESSION_RISK,
    Regime.DEFENSIVE_ROTATION,
    Regime.VALUE_ROTATION,
}

MIN_CASH = 0.10
MAX_CASH = 0.50


def expected_risk_on(probabilities: dict[str, float]) -> float:
    """Probability-weighted risk-on over the FULL regime distribution.

    Precision upgrade over argmax: when the call is contested (e.g. 0.22 vs 0.19),
    winner-take-all flips the whole book on a 3%p margin; the expectation moves
    smoothly with the evidence, and REGIME_UNCERTAIN (risk-on 0) naturally pulls
    toward neutral. Deterministic."""
    by_value = {r.value: r for r in Regime}
    return sum(
        _RISK_ON.get(by_value[k], 0.0) * p for k, p in probabilities.items() if k in by_value
    )


@dataclass(frozen=True)
class WeightDefaults:
    accuracy: float = 0.6
    calibration: float = 0.7
    horizon_suitability: float = 1.0
    independence_haircut: float = 0.9


_DEFAULT_WEIGHTS = WeightDefaults()


def _regime_suitability(regime: Regime, watcher: Watcher) -> float:
    if regime in _FED_DRIVEN:
        return {Watcher.FED_WATCHER: 1.0, Watcher.US_WATCHER: 0.9}.get(watcher, 0.7)
    if regime in _USD_DRIVEN:
        return {Watcher.KRW_WATCHER: 1.0, Watcher.FED_WATCHER: 0.8}.get(watcher, 0.7)
    if regime in _EQUITY_DRIVEN:
        return {Watcher.US_WATCHER: 1.0, Watcher.KOSPI_WATCHER: 1.0}.get(watcher, 0.8)
    if regime is Regime.KOREA_DECOUPLING:
        return {Watcher.KOSPI_WATCHER: 1.0, Watcher.US_WATCHER: 1.0, Watcher.KRW_WATCHER: 0.9}.get(
            watcher, 0.7
        )
    if regime is Regime.LIQUIDITY_STRESS:
        return {Watcher.US_WATCHER: 1.0, Watcher.KRW_WATCHER: 0.9}.get(watcher, 0.8)
    return 0.8


def compute_watcher_weights(
    regime: RegimeAssessment,
    signals: list[NormalizedSignal],
    *,
    accuracy: dict[Watcher, float] | None = None,
    defaults: WeightDefaults | None = None,
) -> tuple[WatcherWeight, ...]:
    defaults = defaults or _DEFAULT_WEIGHTS
    acc = accuracy or {}
    present: dict[Watcher, list[NormalizedSignal]] = {}
    for s in signals:
        w = _TARGET_WATCHER_GROUP.get(s.target)
        if w is not None:
            present.setdefault(w, []).append(s)

    raw: dict[Watcher, tuple[float, dict[str, float]]] = {}
    for watcher, sigs in present.items():
        freshness = sum(x.data_quality.freshness_score for x in sigs) / len(sigs)
        suitability = _regime_suitability(regime.primary_regime, watcher)
        independence = 1.0
        for a, b in _CORRELATED:
            if watcher in (a, b) and a in present and b in present:
                independence = defaults.independence_haircut
        components = {
            # real out-of-sample hit rate when available, else neutral default.
            # Clamped to [0.4, 0.85] so a spurious 0%/100% can't dominate the weighting.
            "accuracy": round(max(0.4, min(0.85, acc.get(watcher, defaults.accuracy))), 4),
            "regime_suitability": suitability,
            "horizon_suitability": defaults.horizon_suitability,
            "freshness": round(freshness, 4),
            "independence": independence,
            "calibration": defaults.calibration,
        }
        weight = 1.0
        for v in components.values():
            weight *= v
        raw[watcher] = (weight, components)

    total = sum(w for w, _ in raw.values()) or 1.0
    return tuple(
        WatcherWeight(watcher=w, weight=round(weight / total, 4), components=comp)
        for w, (weight, comp) in sorted(raw.items(), key=lambda kv: kv[0].value)
    )


def _allocations(
    regime: Regime, risk_on: float, cash: float
) -> tuple[dict[str, float], dict[str, float], dict[str, float], dict[str, float]]:
    remaining = 1.0 - cash
    equity_frac = max(0.15, min(0.85, 0.55 + 0.35 * risk_on))
    equity = round(remaining * equity_frac, 4)
    bond = round(remaining - equity, 4)
    asset_class = {"EQUITY": equity, "BOND": bond, "CASH": round(cash, 4)}

    kr_bias = 0.0
    if regime in {Regime.KRW_STRENGTH, Regime.KOREA_DECOUPLING}:
        kr_bias = 0.10
    elif regime in {Regime.US_TECH_LEADERSHIP, Regime.USD_STRENGTH}:
        kr_bias = -0.10
    kr = max(0.1, min(0.9, 0.45 + kr_bias))
    country = {
        "KOREA": round(remaining * kr, 4),
        "US": round(remaining * (1 - kr), 4),
        "CASH": round(cash, 4),
    }

    growth = 0.0
    if regime in {Regime.US_TECH_LEADERSHIP, Regime.GOLDILOCKS}:
        growth = 0.10
    elif regime in {Regime.VALUE_ROTATION, Regime.HAWKISH_SLOWDOWN, Regime.STAGFLATION}:
        growth = -0.10
    style = {"GROWTH": round(growth, 4), "VALUE": round(-growth, 4)}

    sector: dict[str, float] = {}
    if regime is Regime.US_TECH_LEADERSHIP:
        sector = {"SEMICONDUCTOR": 0.05}
    elif regime is Regime.VALUE_ROTATION:
        sector = {"BANKS": 0.03}
    elif regime is Regime.RECESSION_RISK:
        sector = {"DEFENSIVES": 0.04}
    return asset_class, country, style, sector


def _disagreements(regime: RegimeAssessment, signals: list[NormalizedSignal]) -> tuple[str, ...]:
    out: list[str] = []
    if regime.contradictory_signals:
        n = len(regime.contradictory_signals)
        out.append(f"{n} signal(s) contradict {regime.primary_regime.value}")
    f = extract_features(signals)
    if {"US_EQUITY", "KR_EQUITY"} <= f.groups_present and f.us_equity * f.kospi_equity < 0:
        out.append("US and Korea equity signals point opposite directions")
    if regime.transition_risk >= 0.6:
        out.append(f"high regime-transition risk ({regime.transition_risk:.0%})")
    return tuple(out)


def _strategy_brief(
    regime: RegimeAssessment, risk_on: float, cash: float, targets: list[TargetExposure]
) -> str:
    reg = regime_ko(regime.primary_regime)
    # thresholds sized for the expectation scale (smaller magnitudes than argmax)
    tone = "공격적" if risk_on >= 0.15 else "방어적" if risk_on <= -0.15 else "중립"
    ups = [t.exposure for t in targets if t.direction is ExposureDirection.INCREASE][:3]
    downs = [t.exposure for t in targets if t.direction is ExposureDirection.REDUCE][:3]
    up_s = ", ".join(ups) if ups else "없음"
    down_s = ", ".join(downs) if downs else "없음"
    return (
        f"오늘의 전략 — 시장은 '{reg}' 국면(확신 {regime.confidence:.0%})으로, {tone} 기조가 적절합니다. "
        f"현금은 약 {cash:.0%} 확보한 채, 늘릴 곳은 [{up_s}], 줄일 곳은 [{down_s}]입니다. "
        + (
            "위험선호 국면이라 분할 매수로 위험자산 비중을 키우되 과열 구간은 경계하세요."
            if risk_on >= 0.15
            else "위험회피 국면이라 방어자산(금·달러·국채·현금)으로 무게를 옮기고 위험자산은 줄이세요."
            if risk_on <= -0.15
            else "방향이 엇갈리는 구간이라 한쪽 베팅보다 분산과 현금 여력 확보가 우선입니다."
        )
        + " (매일 갱신되는 참고 전략이며 투자 권유가 아닙니다.)"
    )


def decide(
    regime: RegimeAssessment,
    signals: list[NormalizedSignal],
    accuracy: dict[Watcher, float] | None = None,
) -> CioDecision:
    conf = regime.confidence
    # Expectation over the regime distribution (not argmax). The distribution spread
    # already shrinks the value under uncertainty, so the confidence damping is softer
    # than the old winner-take-all 0.3+0.7c.
    base = expected_risk_on(regime.regime_probabilities)
    risk_on = max(-1.0, min(1.0, base * (0.5 + 0.5 * conf)))
    risk_on_norm = (risk_on + 1.0) / 2.0
    cash = MIN_CASH + (1.0 - risk_on_norm) * (MAX_CASH - MIN_CASH)

    targets: list[TargetExposure] = []
    for exposure, base in _PLAYBOOK.get(regime.primary_regime, []):
        change = base * (0.4 + 0.6 * conf)
        if abs(change) < 1e-9:
            continue
        direction = ExposureDirection.INCREASE if change > 0 else ExposureDirection.REDUCE
        targets.append(
            TargetExposure(
                exposure=exposure,
                direction=direction,
                target_weight_change=str(round(change, 4)),
                horizon=Horizon.M1,
                confidence=conf,
                rationale=f"{regime.primary_regime.value} playbook",
            )
        )

    asset_class, country, style, sector = _allocations(regime.primary_regime, risk_on, cash)
    weights = compute_watcher_weights(regime, signals, accuracy=accuracy)
    cio_id = uuid.uuid5(_NS, f"cio|{regime.regime_id}|{regime.as_of.isoformat()}").hex

    return CioDecision(
        cio_decision_id=cio_id,
        as_of=regime.as_of,
        regime_id=regime.regime_id,
        primary_regime=regime.primary_regime,
        strategy_brief=_strategy_brief(regime, risk_on, cash, targets),
        risk_on_score=round(risk_on, 4),
        target_cash_ratio=round(cash, 4),
        asset_class_allocation=asset_class,
        country_allocation=country,
        style_tilts=style,
        sector_tilts=sector,
        portfolio_confidence=conf,
        disagreements=_disagreements(regime, signals),
        invalidation_conditions=regime.invalidation_conditions,
        watcher_weights=weights,
        targets=tuple(targets),
    )
