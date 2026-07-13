"""International-affairs view builder. Each theme gets a DEEPER individual analysis +
scenarios + asset impact + watch-list; build_geo_view then SYNTHESIZES them (with the
macro regime) into one comprehensive geopolitics report + an overall risk read."""

from __future__ import annotations

from autopilot.domain.enums import Regime, regime_ko
from autopilot.domain.geopolitics.schemas import GeoTheme, GeoView
from autopilot.domain.regime.engine import extract_features
from autopilot.domain.regime.schemas import RegimeAssessment
from autopilot.domain.signals.schemas import NormalizedSignal

_THEMES = (
    GeoTheme(
        title="미·중 전략 경쟁 (반도체·기술 패권)",
        region="미국·중국·대만",
        summary="첨단 반도체 수출통제·공급망 재편·대만 해협 긴장이 구조적으로 장기화되는 흐름입니다.",
        analysis="미국의 대중 첨단 반도체·장비 통제는 단기 협상으로 풀릴 사안이 아니라 '디리스킹(de-risking)'이라는 "
        "구조적 추세입니다. 한국은 반도체 수출국이자 미·중 사이 분업 구조의 한가운데에 있어, 통제 강화는 단기 "
        "수주·매출에 양날의 칼입니다. 대만 리스크는 확률은 낮아도 발생 시 충격이 극단적인 '테일 리스크'입니다.",
        asset_impact="반도체·기술주 변동성 확대. 긴장 고조 시 위험회피로 달러·금 강세, 한국 반도체·중국 노출 자산 약세.",
        scenarios=(
            "완화: 부분 합의·관세 유예 → 반도체·위험자산 안도 랠리",
            "악화: 통제 확대·대만 군사 긴장 → 달러·금·방산 강세, 한국 증시 급락",
        ),
        watch=("추가 수출통제·관세", "대만 해협 군사 활동", "중국 경기부양 강도"),
    ),
    GeoTheme(
        title="중동 정세와 유가",
        region="중동",
        summary="분쟁 위험과 산유국 정책에 따라 유가가 출렁입니다. 유가는 물가·경기·통화정책을 동시에 건드립니다.",
        analysis="유가는 인플레이션의 핵심 변수라, 급등하면 연준·각국 중앙은행의 금리 인하를 지연시켜 위험자산 전반에 "
        "부담을 줍니다. 반대로 안정되면 인하 여력이 생겨 우호적입니다. 호르무즈 해협 물류 차질은 즉각적인 공급 충격 경로입니다.",
        asset_impact="유가 급등 시 물가↑·금리 인하 지연, 에너지주 강세·항공/운송·소비주 약세. 위험회피로 금·달러 수요.",
        scenarios=(
            "안정: 분쟁 제한·증산 → 유가 하향, 인하 기대 회복",
            "급등: 분쟁 확산·호르무즈 차질 → 인플레 재점화, 위험자산 약세",
        ),
        watch=("분쟁 확산 여부", "OPEC+ 감·증산", "호르무즈 해협"),
    ),
    GeoTheme(
        title="러시아-우크라이나 전쟁",
        region="유럽·러시아",
        summary="장기화된 전쟁이 에너지·곡물·방산 공급망에 영향을 줍니다. 휴전/확전 시나리오에 따라 변동성이 큽니다.",
        analysis="전쟁은 유럽 에너지 가격과 글로벌 곡물·비료 공급, 그리고 각국의 방위비 증액 추세를 통해 자산시장에 "
        "작용합니다. 종전·휴전 기대는 유럽 자산과 에너지 안정에 우호적이고, 확전은 안전자산 수요를 키웁니다.",
        asset_impact="유럽 에너지·곡물 가격, 방산주에 직접 영향. 확전 시 달러·금↑, 종전 기대 시 유럽 자산 반등.",
        scenarios=("휴전 진전 → 유럽 위험자산·유로 반등", "확전 → 에너지·곡물 급등, 위험회피"),
        watch=("휴전 협상", "에너지 공급망", "글로벌 방산 수요"),
    ),
    GeoTheme(
        title="미국 정책·재정 (관세·감세·적자)",
        region="미국",
        summary="관세·감세·재정적자 확대 경로가 금리와 달러, 업종 흐름을 좌우합니다. 정치 일정도 변동성 요인입니다.",
        analysis="관세는 수입물가를 통해 인플레이션과 특정 업종 마진에 영향을 주고, 재정적자 확대는 국채 발행 증가로 "
        "장기금리(미국채)와 달러에 부담을 줍니다. 정책 방향에 따라 수혜·피해 업종이 갈리는 '로테이션'이 잦아집니다.",
        asset_impact="관세는 물가·업종 마진, 재정적자는 장기금리·달러에 부담. 정책 수혜/피해 업종 로테이션.",
        scenarios=(
            "관세 강화 → 물가·달러 강세, 수입의존 업종 압박",
            "재정확대 지속 → 장기금리 상승 압력, 성장주 밸류 부담",
        ),
        watch=("관세 발표", "재정적자·국채 발행", "주요 정치 일정"),
    ),
    GeoTheme(
        title="일본은행(BOJ)·엔화 (엔 캐리)",
        region="일본",
        summary="일본의 초완화 정상화 속도와 엔화 방향이 글로벌 자금흐름(엔 캐리)에 영향을 줍니다.",
        analysis="저금리 엔을 빌려 고수익 자산에 투자하는 '엔 캐리'는 글로벌 유동성의 큰 축입니다. BOJ의 급격한 긴축이나 "
        "엔 급등은 이 포지션의 청산을 유발해, 2024년 사례처럼 전 세계 위험자산 변동성을 키울 수 있습니다.",
        asset_impact="엔 강세 급변 시 엔 캐리 청산→글로벌 위험자산 변동성 확대. 한국·신흥국 증시에도 파급.",
        scenarios=(
            "점진 정상화 → 영향 제한적",
            "엔 급등·급한 긴축 → 캐리 청산, 글로벌 변동성 급등",
        ),
        watch=("BOJ 정책 변경", "엔/달러 급변", "엔 캐리 포지션 규모"),
    ),
    GeoTheme(
        title="한반도·코리아 디스카운트",
        region="한국·북한",
        summary="지정학 리스크와 거버넌스 이슈가 한국 자산의 저평가(코리아 디스카운트) 요인으로 작용합니다.",
        analysis="북한 리스크와 지배구조·주주환원 미흡이 한국 증시의 구조적 저평가 요인입니다. 밸류업·거버넌스 개선이 "
        "진전되면 재평가 동력이 되지만, 긴장 고조 시엔 원화 약세와 외국인 매도가 동반됩니다.",
        asset_impact="긴장 고조 시 원화 약세·외국인 매도·방산주 강세. 완화·밸류업 진전 시 한국 증시 재평가.",
        scenarios=("밸류업 진전 → 디스카운트 축소·재평가", "도발·긴장 → 원화 약세·외국인 이탈"),
        watch=("북한 도발", "외국인 수급", "밸류업·거버넌스 정책"),
    ),
    GeoTheme(
        title="중앙은행 정책 차별화",
        region="글로벌",
        summary="미 연준과 다른 중앙은행(ECB·BOK·BOJ 등)의 금리 경로 차이가 환율과 국가 간 자금 이동을 만듭니다.",
        analysis="금리차는 환율의 1차 동인입니다. 미국이 상대적으로 매파면 달러가 강해지고 신흥국에서 자금이 빠집니다. "
        "한국은행이 인상 기조라면 원화엔 지지 요인이지만, 미국과의 금리차·경기 차이를 함께 봐야 합니다.",
        asset_impact="미국이 상대적으로 매파면 달러 강세·신흥국 자금 유출. 인하 전환이 빠른 쪽 통화 약세.",
        scenarios=("미국만 매파 → 달러 독주·신흥국 압박", "동반 완화 → 위험자산 우호"),
        watch=("Fed vs ECB/BOK 금리차", "환율", "신흥국 자금흐름"),
    ),
)

_NOTES = (
    "국제 정세는 전용 데이터 워처가 없어 구조적 테마 분석 + 거시 국면 연동 추론입니다(실시간 이벤트 추적 아님).",
    "위험도·종합은 현재 시장 국면에서 도출한 상대 평가이며, 돌발 이벤트는 별도 모니터링이 필요합니다.",
)

_HIGH = {Regime.LIQUIDITY_STRESS, Regime.RECESSION_RISK, Regime.STAGFLATION}


def build_geo_view(regime: RegimeAssessment, signals: list[NormalizedSignal]) -> GeoView:
    f = extract_features(signals)
    primary = regime.primary_regime
    if primary in _HIGH or f.risk_off >= 0.7:
        level = "높음"
        why = "위험회피·경기/유동성 스트레스 국면 — 지정학 충격이 자산시장에 크게 전이되기 쉽습니다. 달러·금·현금 등 안전판을 의식하세요."
    elif primary is Regime.USD_STRENGTH or regime.transition_risk >= 0.6:
        level = "보통~높음"
        why = "달러 강세·국면 전환 위험이 있어 지정학 이벤트의 파급이 평소보다 큽니다."
    elif primary in {Regime.GOLDILOCKS, Regime.US_TECH_LEADERSHIP} and f.risk_off < 0.3:
        level = "낮음~보통"
        why = "위험선호 국면이라 지정학 노이즈의 시장 충격은 상대적으로 제한적입니다(단, 돌발 변수는 상시 주의)."
    else:
        level = "보통"
        why = "특별한 위험회피 신호는 약하나, 구조적 지정학 리스크는 상존합니다."

    reg = regime_ko(primary)
    if f.usd_strength > 0.1:
        fx_line = "달러 강세 흐름이라 중앙은행 정책 차별화와 미·중 긴장이 신흥국·한국 자산에 더 큰 부담으로 전이됩니다."
    elif f.usd_strength < -0.1:
        fx_line = "달러 약세 흐름이라 신흥국·원화 자산엔 숨통이 트이나, 유가·중동 변수는 여전히 경계 대상입니다."
    else:
        fx_line = "환율이 중립이라 지정학 변수는 개별 이벤트 중심으로 작용합니다."
    synthesis = (
        f"종합하면, 현재 세계 정세의 자산시장 함의는 '{reg}' 국면과 결합해 지정학 위험도 '{level}'로 평가됩니다. "
        f"가장 구조적인 축은 미·중 기술 패권과 중앙은행 정책 차별화이며, 단기 변동성의 방아쇠는 중동·유가와 엔 캐리입니다. "
        f"{fx_line} "
        "리스크가 커지는 국면에서는 금·달러·미국채 같은 안전판과 방산·에너지 같은 사건 대응 자산이 방어력을 제공하고, "
        "긴장이 완화되면 그간 눌렸던 한국·신흥국 위험자산의 반등 탄력이 큽니다."
    )

    return GeoView(
        as_of=regime.as_of,
        risk_level=level,
        risk_rationale=why,
        synthesis=synthesis,
        themes=_THEMES,
        notes=_NOTES,
    )
