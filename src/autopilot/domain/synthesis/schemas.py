"""Cross-watcher synthesis contract. The whole point: the implication of each watcher
*alone* differs from the *combined* read — this surfaces those differences so the user
can survey the entire asset market, not four silos."""

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict

from autopilot.domain.enums import Regime, Watcher


class WatcherTakeaway(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    watcher: Watcher
    label_ko: str
    present: bool
    standalone: str  # what this watcher says on its own
    in_context: str  # what it means once combined with the others


class CrossInsight(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str  # CONFIRMATION | DIVERGENCE | TRANSMISSION | REGIME_NUANCE | UNCERTAINTY
    title: str
    detail: str


class MarketSynthesis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    as_of: AwareDatetime
    primary_regime: Regime
    headline: str
    bottom_line: str
    takeaways: tuple[WatcherTakeaway, ...]
    insights: tuple[CrossInsight, ...]
