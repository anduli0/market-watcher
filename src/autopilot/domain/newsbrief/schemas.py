"""Daily analytical news brief — a synthesized 'third' brief, not a headline list."""

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict


class BriefTheme(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str
    body: str  # synthesized read + implication (not a raw headline)
    items: tuple[str, ...] = ()  # underlying headlines that informed the read


class NewsBrief(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    as_of: AwareDatetime
    title: str
    market_read: str
    themes: tuple[BriefTheme, ...]
    watchlist: tuple[str, ...] = ()
    source_count: int = 0
