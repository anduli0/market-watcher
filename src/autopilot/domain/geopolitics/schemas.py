"""International-affairs (geopolitics) section contract. Curated structural themes +
their asset-market impact, plus a regime-linked overall risk read. Informational +
macro inference — not investment advice."""

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict


class GeoTheme(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str
    region: str
    summary: str
    analysis: str = ""
    asset_impact: str = ""
    scenarios: tuple[str, ...] = ()
    watch: tuple[str, ...] = ()


class GeoView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    as_of: AwareDatetime
    risk_level: str  # 낮음 | 보통 | 높음 (+intermediate)
    risk_rationale: str
    synthesis: str = ""
    themes: tuple[GeoTheme, ...]
    notes: tuple[str, ...] = ()
