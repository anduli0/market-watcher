"""Cross-asset allocation engine — deterministic. Builds an optimal 7-asset portfolio
(달러/미국채/미장/국장/현금/비트코인/금) from the unified regime + the watchers' forward
signals. Bitcoin and gold have no dedicated watcher, so their tilts are derived from the
macro regime/factors (clearly an inference, not a fabricated signal).

Method: start from a diversified NEUTRAL baseline, tilt multiplicatively by a per-asset
attractiveness score scaled by regime confidence, then apply caps/floors and normalize.
Low confidence => stays near the diversified baseline with more cash.
"""

from __future__ import annotations

import math

from autopilot.domain.allocation.schemas import AssetAllocation, CrossAssetPortfolio
from autopilot.domain.cio.engine import expected_risk_on
from autopilot.domain.enums import ASSET_LABEL_KO, AssetClass, Regime
from autopilot.domain.regime.engine import extract_features
from autopilot.domain.regime.schemas import RegimeAssessment
from autopilot.domain.signals.schemas import NormalizedSignal

A = AssetClass

NEUTRAL: dict[AssetClass, float] = {
    A.USD: 0.10,
    A.US_TREASURY: 0.15,
    A.US_EQUITY: 0.25,
    A.KOREA_EQUITY: 0.15,
    A.CASH: 0.10,
    A.BITCOIN: 0.05,
    A.GOLD: 0.20,
}
CAP: dict[AssetClass, float] = {A.BITCOIN: 0.15, A.GOLD: 0.30}
CASH_FLOOR = 0.05


def _pos(x: float) -> float:
    return max(0.0, x)


def _neg(x: float) -> float:
    return max(0.0, -x)


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _usd_view(regime: RegimeAssessment, signals: list[NormalizedSignal]) -> float:
    """USD strong (+) / KRW strong (-), nudged by an explicit FX regime."""
    usd = _clamp(extract_features(signals).usd_strength)
    if regime.primary_regime is Regime.USD_STRENGTH:
        return max(usd, 0.5)
    if regime.primary_regime is Regime.KRW_STRENGTH:
        return min(usd, -0.5)
    return usd


def _scores(regime: RegimeAssessment, signals: list[NormalizedSignal]) -> dict[AssetClass, float]:
    f = extract_features(signals)
    # Probability-weighted expectation over the regime distribution (not argmax) —
    # contested calls tilt proportionally instead of flipping the whole book.
    r = expected_risk_on(regime.regime_probabilities)  # risk-on (+) .. risk-off (-)
    h = _clamp(f.fed_stance)  # hawkish (+) .. dovish (-)
    usd = _usd_view(regime, signals)  # USD strong (+) / KRW strong (-), regime-nudged
    eq_us, eq_kr = f.us_equity, f.kospi_equity
    infl = 1.0 if regime.primary_regime in {Regime.REINFLATION, Regime.STAGFLATION} else 0.0
    liq = (
        1.0
        if regime.primary_regime is Regime.LIQUIDITY_STRESS
        else 0.5
        if regime.primary_regime is Regime.RECESSION_RISK
        else 0.0
    )
    return {
        # Dollar is the safe haven when the won weakens / under uncertainty.
        A.USD: 0.55 * usd
        + 0.35 * _neg(r)
        + 0.25 * _pos(h)
        - 0.25 * _pos(r)
        + 0.25 * regime.transition_risk * _pos(usd),
        A.US_TREASURY: 0.65 * _neg(h) + 0.45 * _neg(r) - 0.45 * infl,
        # Hawkish rates are an equity headwind (valuation pressure) — temper the overweight.
        A.US_EQUITY: 0.75 * r + 0.45 * eq_us - 0.30 * _pos(h),
        A.KOREA_EQUITY: 0.65 * r + 0.45 * eq_kr - 0.45 * _pos(usd) - 0.20 * _pos(h),
        # KRW cash is PENALIZED when the won is expected to weaken (USD strong): holding
        # won loses purchasing power vs the dollar — defensiveness should move to USD/gold.
        A.CASH: 0.40 * _neg(r)
        + 0.25 * regime.transition_risk
        + 0.20 * (1.0 - regime.confidence)
        - 0.70 * _pos(usd)
        + 0.35 * _neg(usd),
        A.BITCOIN: 0.90 * r - 0.60 * _pos(usd) - 0.45 * _pos(h) - 0.60 * liq,
        A.GOLD: 0.50 * _neg(r) + 0.50 * _neg(h) - 0.30 * _pos(usd) + 0.50 * infl + 0.45 * liq,
    }


def _apply_caps_floors(w: dict[AssetClass, float]) -> dict[AssetClass, float]:
    total = sum(w.values()) or 1.0
    w = {a: v / total for a, v in w.items()}
    # caps: clip and redistribute the excess to uncapped assets, pro-rata
    freed = 0.0
    for a, cap in CAP.items():
        if w[a] > cap:
            freed += w[a] - cap
            w[a] = cap
    if freed > 0:
        base = sum(v for a, v in w.items() if a not in CAP) or 1.0
        for a in w:
            if a not in CAP:
                w[a] += freed * (w[a] / base)
    # cash floor
    if w[A.CASH] < CASH_FLOOR:
        need = CASH_FLOOR - w[A.CASH]
        others = sum(v for a, v in w.items() if a is not A.CASH) or 1.0
        for a in w:
            if a is not A.CASH:
                w[a] -= need * (w[a] / others)
        w[A.CASH] = CASH_FLOOR
    total = sum(w.values()) or 1.0
    return {a: max(0.0, v / total) for a, v in w.items()}


def _stance(weight: float, neutral: float) -> str:
    if weight > neutral * 1.12:
        return "OVERWEIGHT"
    if weight < neutral * 0.88:
        return "UNDERWEIGHT"
    return "NEUTRAL"


def _rationale(
    asset: AssetClass,
    regime: RegimeAssessment,
    sc: dict[AssetClass, float],
    stance: str,
    usd: float,
) -> tuple[str, tuple[str, ...]]:
    reg = regime.primary_regime.value
    d: dict[AssetClass, tuple[str, tuple[str, ...]]] = {
        A.USD: (
            "달러(USD) 보유 — 위험회피·달러 강세 국면의 안전판이자 미국 자산 환헤지"
            if sc[A.USD] > 0
            else "달러(USD) — 위험선호·달러 약세 흐름에서 보유 매력 저하",
            ("달러 강세", "안전자산 수요"),
        ),
        A.US_TREASURY: (
            "완화적 통화정책·경기둔화 시 금리 하락(채권가격 상승) 수혜"
            if sc[A.US_TREASURY] > 0
            else "금리 상방/리플레이션 압력에 듀레이션 부담",
            ("금리 방향", "경기 국면"),
        ),
        A.US_EQUITY: (
            "위험선호·미 증시 주도력에 비중 확대 우위"
            if sc[A.US_EQUITY] > 0
            else "위험회피 국면에서 비중 축소",
            ("위험선호", "미 증시 모멘텀"),
        ),
        A.KOREA_EQUITY: (
            "위험선호+원화 강세 시 외국인 유입 기대"
            if sc[A.KOREA_EQUITY] > 0
            else "달러 강세·위험회피에 수급 부담",
            ("위험선호", "원화/외국인 수급"),
        ),
        A.CASH: (
            (
                "원화 약세 전망 — 원화 현금은 달러 대비 구매력이 깎이므로 비중 축소(방어는 달러로 이동)"
                if usd > 0.15
                else "원화 강세 전망 — 환노출 없는 원화 현금 보유가 유리"
                if usd < -0.15
                else "원화 현금 — 환노출 없는 방어 버퍼(전환 위험·불확실성 대비 드라이파우더)"
            ),
            ("원화 방향", "방어 버퍼"),
        ),
        A.BITCOIN: (
            "위험선호·유동성 확대 국면의 고베타 자산으로 소폭 편입"
            if sc[A.BITCOIN] > 0
            else "달러 강세·긴축·유동성 스트레스에 비중 축소",
            ("위험선호/유동성", "변동성 캡 적용"),
        ),
        A.GOLD: (
            "실질금리 하락·위험회피·인플레이션 헤지 복합 수요"
            if sc[A.GOLD] > 0
            else "달러 강세·실질금리 상방에 매력 제한",
            ("실질금리/달러", "헤지 수요"),
        ),
    }
    base, drivers = d[asset]
    return f"[{reg}·{stance}] {base}", drivers


def build_portfolio(
    regime: RegimeAssessment, signals: list[NormalizedSignal]
) -> CrossAssetPortfolio:
    sc = _scores(regime, signals)
    usd = _usd_view(regime, signals)
    conf = regime.confidence
    gain = 1.1 * (0.4 + 0.6 * conf)  # tilt strength scales with confidence
    raw = {a: NEUTRAL[a] * math.exp(gain * _clamp(sc[a], -1.5, 1.5)) for a in NEUTRAL}
    weights = _apply_caps_floors(raw)

    allocations: list[AssetAllocation] = []
    for a in (A.US_EQUITY, A.KOREA_EQUITY, A.US_TREASURY, A.GOLD, A.USD, A.BITCOIN, A.CASH):
        st = _stance(weights[a], NEUTRAL[a])
        why, drivers = _rationale(a, regime, sc, st, usd)
        allocations.append(
            AssetAllocation(
                asset=a,
                label_ko=ASSET_LABEL_KO[a],
                weight=round(weights[a], 4),
                neutral_weight=NEUTRAL[a],
                stance=st,
                score=round(sc[a], 3),
                rationale=why,
                drivers=drivers,
            )
        )
    allocations.sort(key=lambda x: -x.weight)

    r = expected_risk_on(regime.regime_probabilities)
    top = allocations[0]
    if r >= 0.15:  # expectation scale — smaller magnitudes than the old argmax values
        head = f"위험선호 우위 — {top.label_ko} 중심, 위험자산 비중 확대"
    elif r <= -0.15:
        head = f"위험회피 우위 — {top.label_ko}·금·현금 등 방어자산 비중 확대"
    else:
        head = f"중립·혼조 — {top.label_ko} 우위의 분산 유지, 확신도 {conf:.0%}"

    notes = (
        "‘달러(USD)’는 달러 보유(환차익·안전판), ‘원화 현금’은 환노출 없는 원화 보유 — 역할이 다릅니다.",
        "비트코인·금은 전용 워처가 없어 거시 국면에서 도출한 추론 비중입니다(별도 시세 신호 아님).",
        f"확신도 {conf:.0%} · 커버리지 {regime.coverage:.0%}. 확신이 낮으면 분산을 키우되, "
        "원화 약세 국면의 방어는 원화 현금이 아니라 달러로 가져갑니다.",
    )
    return CrossAssetPortfolio(
        as_of=regime.as_of,
        regime_id=regime.regime_id,
        primary_regime=regime.primary_regime,
        risk_on_score=round(r * (0.5 + 0.5 * conf), 3),  # expectation base — softer damping
        confidence=conf,
        coverage=regime.coverage,
        headline=head,
        allocations=tuple(allocations),
        notes=notes,
        invalidation_conditions=regime.invalidation_conditions,
    )
