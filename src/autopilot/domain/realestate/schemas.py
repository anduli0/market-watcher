"""Real-estate section contract. Korea (concrete 행정동/단지 + links, 광역철도, 청약,
부동산 뉴스) + US (daily-rotated diverse market picks + archive). Rate stance splits BOK
(Korea) vs Fed (US). Informational/educational + bold-but-disclaimed views."""

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict


class RealEstateTopic(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str
    body: str = ""
    bullets: tuple[str, ...] = ()


class RealEstateInstrument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ticker: str
    name: str
    kind: str
    note: str


class RealEstateStance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kr_rate_env: str  # BOK-driven
    us_rate_env: str  # Fed-driven
    kr_stance: str
    us_stance: str
    rationale: str


class KrListing(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    area: str  # 행정동/권역
    complexes: tuple[str, ...]
    note: str
    query: str  # search term for deep-links


class UsMarket(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    region: str
    state: str
    thesis: str
    demand: str
    risks: str
    profile: str  # cash-flow / appreciation / balanced
    best_for: str


class ArchivePick(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    region: str
    reason: str = ""


class ArchiveEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    date: str
    picks: tuple[ArchivePick, ...] = ()


class RealEstateView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    as_of: AwareDatetime
    stance: RealEstateStance
    kr_topics: tuple[RealEstateTopic, ...]
    kr_rail: tuple[RealEstateTopic, ...]
    kr_listings: tuple[KrListing, ...]
    kr_redev: tuple[KrListing, ...]
    kr_redev_pinned: tuple[KrListing, ...] = ()  # 항상 상단 고정(필수 관심구역 + 저평가 성장 베팅)
    kr_strategy: tuple[RealEstateTopic, ...] = ()  # 리스크 선호형(공격적) 투자 전략
    kr_subscriptions: tuple[RealEstateTopic, ...]
    us_markets: tuple[UsMarket, ...]  # today's daily picks
    us_evergreen: tuple[RealEstateTopic, ...]
    us_archive: tuple[ArchiveEntry, ...]  # simplified past picks
    instruments: tuple[RealEstateInstrument, ...]
    regulations: tuple[RealEstateTopic, ...]
    re_news: tuple[str, ...]  # real-estate-specific news (separate from general)
    notes: tuple[str, ...] = ()
