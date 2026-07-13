"""Deterministic analyst-report writer. Plain Korean (avoids jargon) and, crucially,
turns numbers into IMPLICATIONS ("그래서 무엇을 의미하나") rather than listing figures.
Templated from the deterministic engines so the narrative always matches the numbers."""

from __future__ import annotations

from collections.abc import Sequence

from autopilot.domain.allocation.schemas import CrossAssetPortfolio
from autopilot.domain.cio.schemas import CioDecision
from autopilot.domain.enums import regime_ko
from autopilot.domain.regime.schemas import RegimeAssessment
from autopilot.domain.report.schemas import AnalystReport, ReportSection
from autopilot.domain.signals.schemas import NormalizedSignal

_STANCE_KO = {"OVERWEIGHT": "비중 확대", "UNDERWEIGHT": "비중 축소", "NEUTRAL": "중립"}


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def build_report(
    portfolio: CrossAssetPortfolio,
    regime: RegimeAssessment,
    cio: CioDecision,
    signals: Sequence[NormalizedSignal],
    news: Sequence[tuple[str, str]] = (),
) -> AnalystReport:
    reg = regime_ko(regime.primary_regime)
    top = portfolio.allocations[0]
    risk_on = portfolio.risk_on_score

    # ---- 총평 (plain + implication) ----
    if risk_on >= 0.3:
        mood = "위험을 감수하기 좋은 분위기"
        mood_do = f"위험자산({top.label_ko} 등) 비중을 늘리되, 한 번에 사기보다 나눠 담는 편이 안전합니다."
    elif risk_on <= -0.3:
        mood = "몸을 사려야 하는 분위기"
        mood_do = "방어 자산(금·달러·현금·국채) 비중을 늘리고 위험자산은 줄이는 편이 안전합니다."
    else:
        mood = "방향이 뚜렷하지 않은 혼조 분위기"
        mood_do = "한쪽에 크게 베팅하기보다 골고루 나눠 담고 현금을 넉넉히 두는 편이 안전합니다."
    summary = (
        f"한마디로 지금은 '{mood}'입니다. 네 개 시장 신호(미국 금리·환율·한국 증시·미국 증시)를 합쳐 보면 "
        f"'{reg}' 국면이고, 신호들의 확신도는 {_pct(regime.confidence)} 수준입니다. "
        f"그래서 권하는 비중 1위 자산은 {top.label_ko}({_pct(top.weight)})입니다. "
        f"{mood_do}"
    )

    # ---- 자산별 배분 및 근거 (REQUIRED heading) ----
    alloc_bullets = tuple(
        f"{a.label_ko} {_pct(a.weight)} ({_STANCE_KO.get(a.stance, a.stance)}) — {a.rationale}"
        for a in portfolio.allocations
    )

    # ---- 시장 상황 진단 (plain + implication) ----
    if regime.transition_risk >= 0.6:
        trans_msg = (
            f"다만 시장이 다른 국면으로 바뀔 위험이 {_pct(regime.transition_risk)}로 높습니다. "
            "즉 지금 판단이 흔들릴 수 있으니, 비중을 과감하게 싣기보다 여지를 남겨두는 게 좋습니다."
        )
    else:
        trans_msg = f"국면이 바뀔 위험은 {_pct(regime.transition_risk)}로 비교적 낮아, 현재 판단을 유지할 만합니다."
    regime_body = f"지금 시장은 '{reg}' 국면입니다. 쉽게 말해, {_regime_plain(regime)} {trans_msg}"

    # ---- 자산 배분 판단 (plain; was 'Meta-CIO') ----
    cash = cio.target_cash_ratio
    house_body = (
        f"위험을 감수할지 말지를 점수로 보면 {risk_on:+.2f}입니다(+는 공격적, −는 방어적). "
        f"이에 맞춰 현금은 약 {_pct(cash)} 정도 들고 가기를 권합니다. "
        "확신이 낮을수록 현금을 늘려 변동성에 대비하는 뜻입니다."
    )

    # ---- 무엇을 지켜봐야 하나 (plain risk) ----
    risk_bullets: list[str] = []
    if regime.coverage < 1.0:
        risk_bullets.append(
            f"네 시장 중 일부 신호가 빠져(데이터 커버리지 {_pct(regime.coverage)}) 확신이 낮습니다. "
            "→ 비중을 보수적으로."
        )
    for d in cio.disagreements:
        risk_bullets.append(f"신호 간 엇갈림: {d}")
    if not risk_bullets:
        risk_bullets.append("현재 특별히 어긋나는 신호는 없습니다. 정기 점검만 유지하면 됩니다.")
    risk_bullets.append(
        "환율이 크게 움직이거나 미국 금리 방향이 바뀌면 위 판단을 다시 봐야 합니다."
    )

    # ---- 뉴스 흐름 (REQUIRED heading) ----
    news_bullets = tuple(f"[{src}] {txt}" for src, txt in news)[:12]
    news_body = "" if news_bullets else "최근 뉴스 브리핑을 불러오지 못했습니다(서비스 일시 불가)."

    sections = (
        ReportSection(
            heading="자산별 배분 및 근거",
            body="7개 자산에 어느 정도 비중을 두면 좋을지와 그 이유입니다(비중·중립 대비 방향·근거).",
            bullets=alloc_bullets,
        ),
        ReportSection(heading="시장 상황 진단", body=regime_body),
        ReportSection(heading="자산 배분 판단", body=house_body),
        ReportSection(heading="무엇을 지켜봐야 하나", bullets=tuple(risk_bullets)),
        ReportSection(heading="뉴스 흐름", body=news_body, bullets=news_bullets),
        ReportSection(
            heading="면책",
            body=(
                "이 글은 공개 데이터와 자동 모델로 만든 참고 자료이며 투자 권유가 아닙니다. "
                "비트코인·금 비중은 거시 흐름에서 추론한 값입니다. © 2026 YellowScale."
            ),
        ),
    )
    return AnalystReport(
        as_of=portfolio.as_of,
        title="MARKET WATCHER — 자산시장 종합 애널리스트 리포트",
        headline=portfolio.headline,
        summary=summary,
        sections=sections,
    )


def _regime_plain(regime: RegimeAssessment) -> str:
    """One plain sentence on what the regime means for an investor."""
    from autopilot.domain.enums import Regime

    table = {
        Regime.GOLDILOCKS: "경기는 완만히 좋고 물가 부담은 낮아 주식에 우호적입니다.",
        Regime.HAWKISH_GROWTH: "금리는 높지만 경기가 받쳐줘 주식이 버틸 수 있는 환경입니다.",
        Regime.HAWKISH_SLOWDOWN: "금리 부담에 경기까지 식고 있어 주식보다 채권·현금이 유리합니다.",
        Regime.REINFLATION: "물가가 다시 오르는 흐름이라 금·실물·단기채가 상대적으로 낫습니다.",
        Regime.STAGFLATION: "경기는 식는데 물가는 올라 가장 까다로운 국면입니다(금·달러·현금 선호).",
        Regime.RECESSION_RISK: "경기침체 위험이 커 안전자산(국채·금·현금) 중심이 안전합니다.",
        Regime.LIQUIDITY_STRESS: "시중에 돈이 마르는 위험 신호라 현금·달러 등 안전판이 중요합니다.",
        Regime.POLICY_EASING_TRANSITION: "금리 인하로 돌아서는 길목이라 채권·성장주에 우호적입니다.",
        Regime.USD_STRENGTH: "달러가 강해(원화는 약해) 달러 자산이 유리하고 원화 보유는 불리합니다.",
        Regime.KRW_STRENGTH: "원화가 강해 한국 자산·원화 보유가 상대적으로 유리합니다.",
        Regime.KOREA_DECOUPLING: "한국과 미국 증시가 따로 움직여, '미국 따라 사기'가 통하지 않는 구간입니다.",
        Regime.US_TECH_LEADERSHIP: "미국 기술주가 시장을 이끌어 관련 자산이 상대적으로 강합니다.",
        Regime.VALUE_ROTATION: "성장주에서 가치주로 자금이 옮겨가는 흐름입니다.",
        Regime.DEFENSIVE_ROTATION: "경기 민감주에서 방어주로 자금이 옮겨가는 흐름입니다.",
        Regime.REGIME_UNCERTAIN: "신호가 엇갈려 방향을 단정하기 어렵습니다. 분산과 현금이 답입니다.",
    }
    return table.get(regime.primary_regime, "")
