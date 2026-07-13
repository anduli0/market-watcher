"""AI 수석 브리프 — grounding payload, prompt, schema validation.

Token discipline: the grounding is a compact Korean-keyed JSON of the deterministic
pipeline's own numbers (no raw watcher payloads), news is capped and truncated, and
one KO-only call produces the whole brief. The model is forbidden from adding facts
not present in the grounding.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, field_validator

from autopilot.domain.enums import ExposureDirection, regime_ko
from autopilot.domain.time import to_kst

if TYPE_CHECKING:
    from autopilot.pipeline import PipelineResult


class AiBrief(BaseModel):
    """Validated shape of one daily AI brief (all plain Korean)."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    headline: str
    summary: tuple[str, ...]
    market_diagnosis: str
    allocation_comment: str
    risks: tuple[str, ...]
    watch_next: tuple[str, ...]
    disclaimer: str

    @field_validator("headline", "market_diagnosis", "allocation_comment", "disclaimer")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("empty field")
        return v

    @field_validator("summary")
    @classmethod
    def _summary_len(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        items = tuple(x.strip() for x in v if x.strip())
        if not (3 <= len(items) <= 6):
            raise ValueError(f"summary must be 3-6 bullets, got {len(items)}")
        return items

    @field_validator("risks", "watch_next")
    @classmethod
    def _list_len(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        items = tuple(x.strip() for x in v if x.strip())
        if not (2 <= len(items) <= 5):
            raise ValueError(f"need 2-5 bullets, got {len(items)}")
        return items


def build_grounding(r: PipelineResult) -> dict[str, Any]:
    """Compact, Korean-keyed grounding from the deterministic pipeline result."""
    reg = r.regime
    w = r.world_view
    top_probs = sorted(reg.regime_probabilities.items(), key=lambda kv: -kv[1])[:4]
    ups = [t.exposure for t in r.cio.targets if t.direction is ExposureDirection.INCREASE][:3]
    downs = [t.exposure for t in r.cio.targets if t.direction is ExposureDirection.REDUCE][:3]
    return {
        "기준시각": to_kst(r.as_of).strftime("%Y-%m-%d %H:%M"),
        "시장국면": {
            "1순위": regime_ko(reg.primary_regime),
            "2순위": regime_ko(reg.secondary_regime) if reg.secondary_regime else None,
            "확신도": round(reg.confidence, 2),
            "전환위험": round(reg.transition_risk, 2),
            "커버리지": round(reg.coverage, 2),
            "상위확률": {k: round(v, 3) for k, v in top_probs},
        },
        "세계조망": {
            "헤드라인": w.headline,
            "종합위험선호(-1~+1)": round(w.converged_risk_on, 2),
            "합의": list(w.consensus)[:3],
            "이견": list(w.dissent)[:3],
        },
        "권고배분_7자산": [
            {"자산": a.label_ko, "비중": round(a.weight, 3), "스탠스": a.stance}
            for a in r.portfolio.allocations
        ],
        "투자전략": {
            "위험선호점수": r.cio.risk_on_score,
            "목표현금비중": r.cio.target_cash_ratio,
            "늘릴곳": ups,
            "줄일곳": downs,
            "상충신호": list(r.cio.disagreements)[:3],
        },
        "뉴스": [f"[{src}] {txt[:90]}" for src, txt in r.news[:8]],
        "종합결론": r.synthesis.bottom_line,
    }


def grounding_hash(r: PipelineResult) -> str:
    """Stable hash of the decision-relevant inputs (timestamps excluded) so an
    unchanged market state never triggers a second paid synthesis."""
    basis = {
        "regime": r.regime.primary_regime.value,
        "secondary": r.regime.secondary_regime.value if r.regime.secondary_regime else None,
        "alloc": [(a.asset.value, round(a.weight, 2), a.stance) for a in r.portfolio.allocations],
        "risk_on": round(r.cio.risk_on_score, 1),
        "cash": round(r.cio.target_cash_ratio, 2),
        "news": sorted(txt[:60] for _src, txt in r.news[:8]),
    }
    raw = json.dumps(basis, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


_SCHEMA_HINT = json.dumps(
    {
        "headline": "시장 전체를 요약하는 한 문장",
        "summary": ["핵심 요점 3~6개(각 1문장)"],
        "market_diagnosis": "시장 종합 진단 3~5문장",
        "allocation_comment": "7자산 권고 배분에 대한 해설 3~5문장",
        "risks": ["주시할 위험 2~5개"],
        "watch_next": ["다음에 확인할 것 2~5개"],
        "disclaimer": "참고 자료이며 투자 권유가 아니라는 한 문장",
    },
    ensure_ascii=False,
)


def build_prompt(grounding: dict[str, Any]) -> str:
    g = json.dumps(grounding, ensure_ascii=False, separators=(",", ":"))
    return f"""당신은 MARKET WATCHER(자산시장 종합 애널리스트 플랫폼)의 수석 애널리스트입니다.
아래 입력은 오늘의 결정론적 분석 결과(시장 국면·자산배분·전략·뉴스)입니다. 이 입력만 근거로 데일리 브리프를 작성하세요.

반드시 지킬 규칙:
- 입력에 없는 사실·수치·사건·이름은 절대 지어내지 않는다.
- 인용하는 숫자는 입력의 숫자와 정확히 일치시킨다.
- 모든 문장은 평이한 한국어로 쓴다. 학술 용어나 영어 음차(예: 레짐, 모멘텀, 리스크온)를 피하고 쉬운 표현(예: 시장 국면, 상승 흐름, 위험선호)을 쓴다. 문장은 짧고 명확하게.
- 숫자 나열이 아니라, 숫자가 의미하는 바(그래서 무엇을 해야 하는가)를 풀어 쓴다.
- 전체 분량은 500~900자. JSON 하나만 출력한다(앞뒤 설명·코드블록 금지).

오늘의 입력:
{g}

다음 형태의 JSON으로만 응답:
{_SCHEMA_HINT}"""


def corrective_retry(prompt: str, error: Exception) -> str:
    return (
        prompt
        + f"\n\n직전 응답이 검증에 실패했습니다: {error}. 수정된 JSON 하나만 다시 출력하세요."
    )


def validate_brief(data: dict[str, Any]) -> AiBrief:
    return AiBrief.model_validate(data)
