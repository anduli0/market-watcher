"""Cross-watcher synthesis engine — deterministic. Contrasts each watcher's standalone
read with the integrated read, and extracts the cross-market insights that only appear
when the four are combined (divergence, FX transmission, regime nuance, confirmation)."""

from __future__ import annotations

from autopilot.domain.enums import Watcher, regime_ko
from autopilot.domain.regime.engine import extract_features
from autopilot.domain.regime.schemas import RegimeAssessment
from autopilot.domain.signals.schemas import NormalizedSignal
from autopilot.domain.synthesis.schemas import CrossInsight, MarketSynthesis, WatcherTakeaway

_LABEL = {
    Watcher.FED_WATCHER: "미 연준 · 금리",
    Watcher.KRW_WATCHER: "원/달러 환율",
    Watcher.KOSPI_WATCHER: "한국 증시(국장)",
    Watcher.US_WATCHER: "미국 증시(미장)",
}


def _sgn(x: float, band: float = 0.1) -> int:
    return 1 if x > band else (-1 if x < -band else 0)


def build_synthesis(regime: RegimeAssessment, signals: list[NormalizedSignal]) -> MarketSynthesis:
    f = extract_features(signals)
    fed, usd = _sgn(f.fed_stance), _sgn(f.usd_strength)
    us, kr = _sgn(f.us_equity), _sgn(f.kospi_equity)
    present = f.groups_present

    standalone = {
        Watcher.FED_WATCHER: {1: "금리 상방(매파)", -1: "금리 하방(완화)", 0: "동결·중립"}[fed],
        Watcher.KRW_WATCHER: {1: "원화 약세·달러 강세", -1: "원화 강세·달러 약세", 0: "환율 중립"}[
            usd
        ],
        Watcher.KOSPI_WATCHER: {1: "국장 강세", -1: "국장 약세", 0: "국장 중립"}[kr],
        Watcher.US_WATCHER: {1: "미장 강세", -1: "미장 약세", 0: "미장 혼조"}[us],
    }
    group_key = {
        Watcher.FED_WATCHER: "FED",
        Watcher.KRW_WATCHER: "USD",
        Watcher.US_WATCHER: "US_EQUITY",
        Watcher.KOSPI_WATCHER: "KR_EQUITY",
    }
    context = {
        Watcher.FED_WATCHER: (
            "매파 신호라도 위험회피가 겹치면 '주식↓'보다 미국채·현금 선호로 읽어야 합니다."
            if fed > 0
            else "완화 기대는 미국채·금·성장주에 우호적이나 달러 약세 여부를 함께 봐야 합니다."
        ),
        Watcher.KRW_WATCHER: (
            "달러 강세는 미장 언헤지 환차익을 키우는 동시에 국장 외국인 수급엔 부담 — 같은 사건이 자산별로 반대로 작용합니다."
            if usd > 0
            else "원화 강세는 국장·신흥국에 우호적이며, 미장 언헤지 환차손 요인입니다."
        ),
        Watcher.US_WATCHER: (
            "미장 강세를 그대로 국장에 대입하면 오류 — 환율·디커플링을 거쳐야 한국 자산 함의가 정해집니다."
            if us > 0
            else "미장 약세는 위험회피로 전이되며 국장·비트코인에 하방 압력입니다."
        ),
        Watcher.KOSPI_WATCHER: (
            "국장 강세가 미장과 엇갈리면 단순 동조가 아니라 디커플링 — 비중 확대는 신중해야 합니다."
            if kr > 0
            else "국장 약세는 달러 강세·외국인 매도와 함께 나타나는지 확인이 필요합니다."
        ),
    }

    takeaways = tuple(
        WatcherTakeaway(
            watcher=w,
            label_ko=_LABEL[w],
            present=group_key[w] in present,
            standalone=standalone[w] if group_key[w] in present else "신호 없음(워처 미가용/만료)",
            in_context=context[w]
            if group_key[w] in present
            else "해당 시장 신호 부재 — 종합 확신을 낮춥니다.",
        )
        for w in (
            Watcher.FED_WATCHER,
            Watcher.KRW_WATCHER,
            Watcher.US_WATCHER,
            Watcher.KOSPI_WATCHER,
        )
    )

    insights: list[CrossInsight] = []
    if {"US_EQUITY", "KR_EQUITY"} <= present and us * kr < 0:
        insights.append(
            CrossInsight(
                kind="DIVERGENCE",
                title="미장 ↔ 국장 디커플링",
                detail="미국과 한국 증시 신호가 반대입니다. '미국 따라 산다'는 단순 가정이 깨지는 구간으로, "
                "환율·외국인 수급·반도체 사이클 차이를 확인하기 전엔 한국 비중을 늘리지 않는 편이 안전합니다.",
            )
        )
    if "USD" in present and usd != 0 and (("US_EQUITY" in present) or ("KR_EQUITY" in present)):
        insights.append(
            CrossInsight(
                kind="TRANSMISSION",
                title="환율이 미국 매크로를 한국 자산으로 전달",
                detail=(
                    "달러 강세 국면: 미장 상승은 원화 투자자에게 환차익으로 증폭(언헤지 유리)되지만, "
                    "같은 달러 강세가 국장 외국인 수급엔 역풍입니다. 단일 시장만 보면 이 연결을 놓칩니다."
                    if usd > 0
                    else "달러 약세 국면: 국장·신흥국에 우호적이고, 미장 언헤지 포지션은 환차손에 노출됩니다."
                ),
            )
        )
    if fed > 0 and (us < 0 or kr < 0):
        insights.append(
            CrossInsight(
                kind="REGIME_NUANCE",
                title="둔화발 금리 — '금리↑=주식↓' 단순화 금지",
                detail="금리 상방과 증시 약세가 동시에 나타납니다. 성장발 금리 상승이면 주식과 양립하지만, "
                "지금은 둔화발에 가까워 미국채·현금·금 선호로 읽는 것이 정합적입니다.",
            )
        )
    equities = [v for v, g in ((us, "US_EQUITY"), (kr, "KR_EQUITY")) if g in present]
    if equities and all(v > 0 for v in equities) and fed <= 0:
        insights.append(
            CrossInsight(
                kind="CONFIRMATION",
                title="위험선호 정렬 — 분산된 확인",
                detail="증시 신호가 위험선호로 정렬되고 금리도 비우호적이지 않습니다. 네 워처가 같은 방향을 가리킬수록 "
                "단일 신호보다 확신이 높아져 위험자산 비중확대 신뢰도가 올라갑니다.",
            )
        )
    if regime.transition_risk >= 0.5 or regime.coverage < 1.0:
        insights.append(
            CrossInsight(
                kind="UNCERTAINTY",
                title="신호 엇갈림·부재 → 종합 확신 하향",
                detail=f"전환 위험 {regime.transition_risk:.0%}, 커버리지 {regime.coverage:.0%}. "
                "개별 워처가 또렷해 보여도 종합하면 확신이 제한되므로 현금·분산 비중을 키우는 것이 합리적입니다.",
            )
        )
    if not insights:
        insights.append(
            CrossInsight(
                kind="CONFIRMATION",
                title="신호 일관",
                detail="워처 간 큰 상충이 없습니다. 종합 함의가 개별 함의와 대체로 일치합니다.",
            )
        )

    naive = standalone[Watcher.US_WATCHER] if "US_EQUITY" in present else "미장 신호"
    reg_ko = regime_ko(regime.primary_regime)
    bottom = (
        f"개별로는 '{naive}' 같은 신호가 두드러지지만, 종합하면 '{reg_ko}' 국면"
        f"(확신 {regime.confidence:.0%})입니다. 단일 시장만 보면 환율 전이·한·미 디커플링·"
        "둔화 속 금리 같은 교차 효과를 놓치기 쉬우므로, 자산배분은 종합 신호에 맞춰야 합니다."
    )
    head = f"4개 워처 종합 — '{reg_ko}' 국면, 교차 인사이트 {len(insights)}건"
    return MarketSynthesis(
        as_of=regime.as_of,
        primary_regime=regime.primary_regime,
        headline=head,
        bottom_line=bottom,
        takeaways=takeaways,
        insights=tuple(insights),
    )
