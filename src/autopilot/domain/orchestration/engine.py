"""MARKET WATCHER orchestration engine — deterministic.

Sector desks form opinions from the collected signals + delegate intel; a chief
reconciles them; a convergence loop feeds the global read back onto each market
(confirming views gain weight, dissenting low-conviction views fade) and recomputes
until the per-market reads and the global read converge. No LLM, reproducible."""

from __future__ import annotations

from collections.abc import Sequence

from autopilot.domain.enums import Watcher, regime_ko
from autopilot.domain.orchestration.schemas import (
    ConvergenceRound,
    DeskOpinion,
    WatcherIntel,
    WorldView,
)
from autopilot.domain.regime.engine import extract_features
from autopilot.domain.regime.schemas import RegimeAssessment
from autopilot.domain.signals.schemas import NormalizedSignal


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _risk_label(g: float) -> str:
    if g >= 0.25:
        return "위험선호 우위"
    if g <= -0.25:
        return "위험회피 우위"
    return "중립·혼조"


def _dir_label(x: float, up: str, down: str, mid: str = "중립") -> str:
    return up if x > 0.1 else down if x < -0.1 else mid


def _conv(strength: float, present: bool, notes: int) -> float:
    base = 0.30 + 0.50 * min(1.0, abs(strength))
    base *= 1.0 if present else 0.4
    return _clamp(base + 0.02 * notes, 0.0, 0.95)


def _build_desks(
    regime: RegimeAssessment,
    signals: list[NormalizedSignal],
    intel: Sequence[WatcherIntel],
) -> list[DeskOpinion]:
    f = extract_features(signals)
    notes = {i.watcher: len(i.notes) for i in intel}
    p = f.groups_present
    fed, usd, us, kr = (
        _clamp(f.fed_stance),
        _clamp(f.usd_strength),
        _clamp(f.us_equity),
        _clamp(f.kospi_equity),
    )
    risk_off, trans, div = f.risk_off, regime.transition_risk, f.divergence_kr_us

    return [
        DeskOpinion(
            desk="RATES",
            label_ko="금리·연준 데스크",
            lean_label=_dir_label(fed, "긴축(매파)", "완화(비둘기)"),
            lean_score=_clamp(-fed),
            conviction=_conv(fed, "FED" in p, notes.get(Watcher.FED_WATCHER, 0)),
            summary="연준 경로가 매파면 위험자산에 부담, 완화면 채권·성장주에 우호적입니다.",
            drivers=("미 정책금리 경로", "장단기 금리"),
            dissent="완화 신호가 둔화 신호와 겹치면 해석이 갈립니다.",
        ),
        DeskOpinion(
            desk="FX",
            label_ko="환율·달러 데스크",
            lean_label=_dir_label(usd, "달러 강세(원화 약세)", "원화 강세"),
            lean_score=_clamp(-0.7 * usd),
            conviction=_conv(usd, "USD" in p, notes.get(Watcher.KRW_WATCHER, 0)),
            summary="달러 강세는 미국 자산(언헤지)엔 유리하나 한국 증시 수급엔 역풍입니다.",
            drivers=("달러 방향", "외국인 수급"),
            dissent="안전통화 수요와 무역흐름이 반대로 작용할 수 있습니다.",
        ),
        DeskOpinion(
            desk="US_EQ",
            label_ko="미국 증시 데스크",
            lean_label=_dir_label(us, "강세", "약세", "혼조"),
            lean_score=_clamp(us),
            conviction=_conv(us, "US_EQUITY" in p, notes.get(Watcher.US_WATCHER, 0)),
            summary="미국 증시 방향은 글로벌 위험선호의 기준점입니다.",
            drivers=("미 지수·breadth", "기술주 주도"),
            dissent="지수 강세가 소수 종목 쏠림이면 신뢰도가 낮습니다.",
        ),
        DeskOpinion(
            desk="KR_EQ",
            label_ko="한국 증시 데스크",
            lean_label=_dir_label(kr, "강세", "약세", "혼조"),
            lean_score=_clamp(kr),
            conviction=_conv(kr, "KR_EQUITY" in p, notes.get(Watcher.KOSPI_WATCHER, 0)),
            summary="한국 증시는 환율·외국인·반도체 사이클에 민감합니다.",
            drivers=("외국인 수급", "반도체"),
            dissent="미국과 따로 움직이면(디커플링) 동조 가정이 깨집니다.",
        ),
        DeskOpinion(
            desk="CROSS",
            label_ko="크로스에셋 데스크",
            lean_label="동조" if div < 0.4 else "디커플링 경계",
            lean_score=_clamp(0.5 * f.equity - 0.5 * div),
            conviction=_clamp(0.45 + 0.3 * (1 - div), 0.0, 0.9),
            summary="시장 간 신호가 일치하면 확신을 키우고, 엇갈리면 분산·현금을 권합니다.",
            drivers=("미·한 동조도", "환율 전이"),
            dissent="시차·ETF 괴리 등 기술적 요인이 디커플링처럼 보일 수 있습니다.",
        ),
        DeskOpinion(
            desk="RISK",
            label_ko="리스크·방어 데스크",
            lean_label=_dir_label(-(0.7 * risk_off + 0.4 * trans), "위험감내 여력", "방어 강화"),
            lean_score=_clamp(-(0.7 * risk_off + 0.4 * trans)),
            conviction=_clamp(0.5 + 0.3 * risk_off + 0.2 * trans, 0.0, 0.95),
            summary="위험회피·전환위험이 높으면 금·달러·현금 등 방어자산을 키웁니다.",
            drivers=("위험회피 강도", "국면 전환 위험", "데이터 커버리지"),
            dissent="과도한 방어는 회복 국면 수익을 놓칠 수 있습니다.",
        ),
    ]


def _sign(x: float, band: float = 0.05) -> int:
    return 1 if x > band else -1 if x < -band else 0


def _converge(desks: list[DeskOpinion]) -> tuple[list[ConvergenceRound], float, bool]:
    weights = [d.conviction for d in desks]
    rounds: list[ConvergenceRound] = []
    prev: float | None = None
    g = 0.0
    converged = False
    for rnd in range(1, 5):
        wsum = sum(weights) or 1.0
        g = sum(d.lean_score * w for d, w in zip(desks, weights, strict=False)) / wsum
        delta = abs(g - prev) if prev is not None else 1.0
        note = (
            "각 데스크 원안을 신뢰도 가중 종합"
            if rnd == 1
            else "글로벌 조망을 각 시장에 환류 — 합의 미달 시각은 비중↓, 일치 시각은 비중↑ 후 재계산"
        )
        rounds.append(
            ConvergenceRound(
                round_no=rnd,
                global_score=round(g, 4),
                global_label=_risk_label(g),
                delta=round(delta, 4),
                note=note,
            )
        )
        if prev is not None and delta < 0.03:
            converged = True
            break
        prev = g
        gsign = _sign(g)
        weights = [
            w * (1.12 if (_sign(d.lean_score) == gsign or gsign == 0) else 0.82)
            for d, w in zip(desks, weights, strict=False)
        ]
    return rounds, g, converged


def build_world_view(
    regime: RegimeAssessment,
    signals: list[NormalizedSignal],
    intel: Sequence[WatcherIntel] = (),
) -> WorldView:
    desks = _build_desks(regime, signals, intel)
    rounds, g, converged = _converge(desks)
    gsign = _sign(g)

    consensus = tuple(d.label_ko for d in desks if _sign(d.lean_score) == gsign and gsign != 0)
    dissent = tuple(d.label_ko for d in desks if _sign(d.lean_score) == -gsign and gsign != 0)
    confidence = _clamp(regime.confidence * 0.7 + (0.3 if converged else 0.12), 0.0, 1.0)

    reg = regime_ko(regime.primary_regime)
    overview = (
        f"네 시장(미국 금리·환율·한국 증시·미국 증시)에서 모은 정보를 데스크별로 검토하고 수석이 조율한 결과, "
        f"세계 경제는 '{reg}' 국면이며 종합 위험선호는 {g:+.2f}({_risk_label(g)})입니다. "
        f"섹터 데스크 {len(consensus)}곳이 같은 방향, {len(dissent)}곳이 반대 의견입니다."
    )
    if converged:
        bottom = (
            f"글로벌 조망을 각 시장에 되돌려 재검토하는 과정을 {len(rounds)}라운드 거쳐 "
            f"개별시장 시각과 전체 시각이 수렴했습니다(최종 {g:+.2f}). "
            "즉 시장 간 신호가 대체로 정합적이라는 뜻입니다."
        )
    else:
        bottom = (
            f"{len(rounds)}라운드 조율에도 시각차가 남아 완전 수렴에 이르지 못했습니다(최종 {g:+.2f}). "
            "시장 간 신호가 엇갈리는 구간이므로 분산과 현금 비중을 키우는 편이 안전합니다."
        )
    headline = (
        f"세계 경제 조망 — {_risk_label(g)} · {'수렴' if converged else '미수렴'}({len(rounds)}R)"
    )

    return WorldView(
        as_of=regime.as_of,
        headline=headline,
        overview=overview,
        bottom_line=bottom,
        converged_risk_on=round(g, 4),
        confidence=confidence,
        converged=converged,
        iterations=len(rounds),
        desks=tuple(desks),
        consensus=consensus,
        dissent=dissent,
        rounds=tuple(rounds),
        intel=tuple(intel),
    )
