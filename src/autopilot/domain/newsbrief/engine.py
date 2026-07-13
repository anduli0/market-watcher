"""Build a deterministic ANALYTICAL daily brief from the day's collected news — it
buckets headlines by theme, synthesizes a read + implication per theme, and ties the
whole to the regime + world view. Real-estate items are excluded (they live in the
부동산 탭). Not a list — a processed 'third' brief."""

from __future__ import annotations

from collections.abc import Sequence

from autopilot.domain.enums import regime_ko
from autopilot.domain.newsbrief.schemas import BriefTheme, NewsBrief
from autopilot.domain.realestate.engine import RE_NEWS_KEYWORDS
from autopilot.domain.regime.schemas import RegimeAssessment

# ordered buckets — first match wins
_BUCKETS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    (
        "통화정책·금리",
        (
            "금리",
            "연준",
            "fed",
            "인상",
            "인하",
            "기준금리",
            "한국은행",
            "bok",
            "통화",
            "rate",
            "inflation",
            "cpi",
            "물가",
            "pce",
        ),
        "금리·물가 흐름은 위험자산 밸류에이션과 환율의 출발점입니다.",
    ),
    (
        "환율·달러",
        ("환율", "달러", "원화", "dollar", "위안", "엔", "fx", "외환"),
        "환율은 외국인 수급과 미국 자산의 원화 환산 손익을 좌우합니다.",
    ),
    (
        "증시·기업",
        (
            "증시",
            "코스피",
            "코스닥",
            "나스닥",
            "s&p",
            "다우",
            "주가",
            "반도체",
            "실적",
            "earnings",
            "stock",
            "equity",
            "ai",
            "엔비디아",
            "삼성",
        ),
        "증시·실적 뉴스는 위험선호의 온도계입니다.",
    ),
    (
        "지정학·국제",
        (
            "중국",
            "미국",
            "전쟁",
            "중동",
            "유가",
            "관세",
            "지정학",
            "대만",
            "북한",
            "war",
            "oil",
            "tariff",
            "russia",
            "우크라이나",
            "ecb",
            "boj",
        ),
        "지정학·정책 이벤트는 안전자산 수요와 변동성의 방아쇠입니다.",
    ),
)


def _bucket(text: str) -> str | None:
    low = text.lower()
    if any(k.lower() in low for k in RE_NEWS_KEYWORDS):
        return None  # real-estate news belongs to the 부동산 탭
    for name, keys, _ in _BUCKETS:
        if any(k.lower() in low for k in keys):
            return name
    return "기타"


def build_news_brief(
    news: Sequence[tuple[str, str]],
    regime: RegimeAssessment,
    risk_on: float,
    world_headline: str,
) -> NewsBrief:
    grouped: dict[str, list[str]] = {}
    for src, text in news:
        b = _bucket(text)
        if b is None:
            continue
        grouped.setdefault(b, []).append(f"[{src}] {text}")

    reg = regime_ko(regime.primary_regime)
    risk_word = "위험선호" if risk_on >= 0.25 else "위험회피" if risk_on <= -0.25 else "중립·혼조"
    dominant = max(grouped, key=lambda k: len(grouped[k])) if grouped else "특이 뉴스 부족"
    market_read = (
        f"오늘 수집한 뉴스 {sum(len(v) for v in grouped.values())}건을 종합하면, 흐름의 무게중심은 "
        f"'{dominant}'에 있습니다. 이를 시장 국면('{reg}', 종합 {risk_word})과 겹쳐 보면 "
        f"{world_headline}. 개별 헤드라인을 나열하기보다, 아래처럼 주제별로 묶어 '그래서 자산에 어떤 의미인지'로 "
        "재해석했습니다."
    )

    _IMPL = {name: impl for name, _keys, impl in _BUCKETS}
    themes: list[BriefTheme] = []
    for name in [b[0] for b in _BUCKETS] + ["기타"]:
        items = grouped.get(name)
        if not items:
            continue
        impl = _IMPL.get(name, "시장 전반의 분위기를 보여주는 신호입니다.")
        body = f"{len(items)}건 — {impl}"
        themes.append(BriefTheme(title=name, body=body, items=tuple(items[:6])))

    if not themes:  # always written: fall back to model analysis when news is sparse
        themes.append(
            BriefTheme(
                title="시장 분석 종합",
                body=(
                    f"오늘은 수집된 일반 뉴스가 적어 모델 분석으로 갈음합니다. {world_headline}. "
                    f"현재 국면은 '{reg}'({risk_word})이며, 뉴스가 부족할수록 가격·지표 신호와 "
                    "분산·현금 비중에 무게를 둡니다."
                ),
                items=(),
            )
        )

    watchlist = [
        f"{reg} 국면의 무효화 조건(환율·금리 방향 전환)",
        "지정학 돌발(중동·대만·엔 캐리)로 인한 변동성 급변",
    ]
    if regime.coverage < 1.0:
        watchlist.append("일부 시장 신호 부재 — 뉴스 해석의 확신도 제한")

    return NewsBrief(
        as_of=regime.as_of,
        title="MARKET WATCHER — 데일리 분석 브리프",
        market_read=market_read,
        themes=tuple(themes),
        watchlist=tuple(watchlist),
        source_count=sum(len(v) for v in grouped.values()),
    )
