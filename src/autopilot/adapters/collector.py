"""Signal collection: run all configured adapters concurrently and assemble a
``SignalSnapshot``. A watcher that fails or returns nothing does NOT abort the
snapshot — it lowers coverage and is recorded in ``errors`` (degradation contract,
ARCHITECTURE §5). No fabricated replacement is produced for a missing watcher.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from autopilot.adapters import ADAPTER_TYPES
from autopilot.adapters.base import WatcherAdapter
from autopilot.domain.enums import Watcher
from autopilot.domain.signals.schemas import NormalizedSignal
from autopilot.domain.time import now_utc


@dataclass(frozen=True)
class WatcherSpec:
    base_url: str
    ttl_seconds: int
    max_age_seconds: int
    enabled: bool = True


def build_adapters(
    specs: dict[Watcher, WatcherSpec],
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[Watcher, WatcherAdapter]:
    adapters: dict[Watcher, WatcherAdapter] = {}
    for watcher, spec in specs.items():
        if not spec.enabled:
            continue
        cls = ADAPTER_TYPES[watcher]
        adapters[watcher] = cls(
            spec.base_url,
            ttl_seconds=spec.ttl_seconds,
            max_age_seconds=spec.max_age_seconds,
            client=client,
        )
    return adapters


@dataclass
class SignalSnapshot:
    collected_at: datetime
    signals: list[NormalizedSignal]
    health: dict[Watcher, bool] = field(default_factory=dict)
    errors: dict[Watcher, list[str]] = field(default_factory=dict)

    @property
    def available_watchers(self) -> set[Watcher]:
        return {w for w, ok in self.health.items() if ok}

    @property
    def coverage(self) -> float:
        """Fraction of configured watchers that produced usable signals."""
        if not self.health:
            return 0.0
        return len(self.available_watchers) / len(self.health)

    def fresh(self, now: datetime | None = None) -> list[NormalizedSignal]:
        ref = now or now_utc()
        return [s for s in self.signals if not s.is_stale(ref)]


async def collect(adapters: dict[Watcher, WatcherAdapter]) -> SignalSnapshot:
    results = await asyncio.gather(*(a.fetch_latest() for a in adapters.values()))
    snapshot = SignalSnapshot(collected_at=now_utc(), signals=[])
    for result in results:
        snapshot.health[result.watcher] = result.ok
        if result.errors:
            snapshot.errors[result.watcher] = result.errors
        snapshot.signals.extend(result.signals)
    return snapshot
