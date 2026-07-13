"""Orchestration contracts — the MARKET WATCHER multi-agent layer.

Delegate agents collect deep intel from each watcher (WatcherIntel); MARKET WATCHER's
own sector desks (DeskOpinion) debate it; a chief reconciles them into a WorldView, run
through a convergence loop (ConvergenceRound) so the per-market reads and the global read
converge. Deterministic — reproducible given identical inputs."""

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from autopilot.domain.enums import Watcher


class WatcherIntel(BaseModel):
    """A delegate agent's report after being 'dispatched' to a watcher (read-only)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    watcher: Watcher
    label_ko: str
    present: bool
    standalone_lean: str
    notes: tuple[str, ...] = ()  # internal agent/desk knowledge collected
    endpoints: tuple[str, ...] = ()  # which watcher endpoints were consulted


class DeskOpinion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    desk: str
    label_ko: str
    lean_label: str
    lean_score: float = Field(ge=-1.0, le=1.0)  # + supportive(risk-on) / - cautious
    conviction: float = Field(ge=0.0, le=1.0)
    summary: str
    drivers: tuple[str, ...] = ()
    dissent: str = ""


class ConvergenceRound(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    round_no: int
    global_score: float
    global_label: str
    delta: float
    note: str


class WorldView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    as_of: AwareDatetime
    headline: str
    overview: str
    bottom_line: str
    converged_risk_on: float = Field(ge=-1.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    converged: bool
    iterations: int
    desks: tuple[DeskOpinion, ...]
    consensus: tuple[str, ...] = ()
    dissent: tuple[str, ...] = ()
    rounds: tuple[ConvergenceRound, ...] = ()
    intel: tuple[WatcherIntel, ...] = ()
