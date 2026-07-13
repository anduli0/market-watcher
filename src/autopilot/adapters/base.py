"""WATCHER adapter base (Phase 1).

Each adapter fetches a watcher's latest-forecast endpoint, validates timestamps,
rejects malformed responses, normalizes into ``NormalizedSignal``s, attaches model
version / source timestamp / data age / TTL, records failures, and preserves the raw
response for audit. ``parse`` is a PURE classmethod (body -> signals) so it can be
contract-tested against captured fixtures with no I/O.
"""

from __future__ import annotations

import asyncio
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar

import httpx

from autopilot.domain.enums import Watcher
from autopilot.domain.signals.schemas import DataQuality, NormalizedSignal
from autopilot.domain.time import now_utc

# Stable namespace so the same (watcher, target, horizon, source_data_at) always
# yields the same signal_id — deterministic parsing + natural dedup.
_SIGNAL_NS = uuid.UUID("a1f0c0de-0000-4000-8000-0bad0bad0bad")


def make_signal_id(watcher: Watcher, target: str, horizon: str, source_data_at: datetime) -> str:
    key = f"{watcher.value}|{target}|{horizon}|{source_data_at.isoformat()}"
    return uuid.uuid5(_SIGNAL_NS, key).hex


def freshness_score(source_data_at: datetime, fetched_at: datetime, ttl_seconds: int) -> float:
    age = (fetched_at - source_data_at).total_seconds()
    if ttl_seconds <= 0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - age / ttl_seconds))


def quality(
    source_data_at: datetime,
    fetched_at: datetime,
    ttl_seconds: int,
    *,
    completeness: float = 1.0,
    source_health: float = 1.0,
) -> DataQuality:
    return DataQuality(
        freshness_score=freshness_score(source_data_at, fetched_at, ttl_seconds),
        completeness_score=max(0.0, min(1.0, completeness)),
        source_health_score=max(0.0, min(1.0, source_health)),
    )


@dataclass(frozen=True)
class RawResponse:
    """The original, unmodified watcher response — preserved for audit."""

    watcher: Watcher
    url: str
    fetched_at: datetime
    status_code: int | None
    body: Any
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.status_code is not None and 200 <= self.status_code < 300


@dataclass
class AdapterResult:
    watcher: Watcher
    fetched_at: datetime
    signals: list[NormalizedSignal]
    raw: RawResponse
    errors: list[str] = field(default_factory=list)
    dropped_stale: int = 0

    @property
    def ok(self) -> bool:
        return self.raw.ok and not self.errors and bool(self.signals)


class WatcherAdapter(ABC):
    watcher: ClassVar[Watcher]

    def __init__(
        self,
        base_url: str,
        *,
        ttl_seconds: int,
        max_age_seconds: int,
        timeout: float = 8.0,
        retries: int = 2,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.ttl_seconds = ttl_seconds
        self.max_age_seconds = max_age_seconds
        self.timeout = timeout
        self.retries = retries
        self._client = client

    @property
    @abstractmethod
    def latest_path(self) -> str: ...

    @property
    @abstractmethod
    def health_path(self) -> str: ...

    @classmethod
    @abstractmethod
    def parse(cls, body: Any, fetched_at: datetime, ttl_seconds: int) -> list[NormalizedSignal]:
        """Pure: map a watcher's raw JSON body into NormalizedSignals.

        Raises ValueError on a malformed body. Must never partially-parse into a
        half-valid signal.
        """

    async def _get(self, path: str) -> RawResponse:
        url = f"{self.base_url}{path}"
        fetched_at = now_utc()
        client = self._client or httpx.AsyncClient(timeout=self.timeout)
        own = self._client is None
        last_err = "no attempt"
        try:
            # Retry transient transport/timeout failures (some watchers are slow under load).
            for attempt in range(self.retries + 1):
                try:
                    resp = await client.get(url)
                    body = resp.json()
                    return RawResponse(self.watcher, url, fetched_at, resp.status_code, body)
                except Exception as exc:  # noqa: BLE001 — transport/JSON error, retry
                    last_err = str(exc) or exc.__class__.__name__
                    if attempt < self.retries:
                        await asyncio.sleep(0.4 * (attempt + 1))
            return RawResponse(self.watcher, url, fetched_at, None, None, error=last_err)
        finally:
            if own:
                await client.aclose()

    async def fetch_latest(self) -> AdapterResult:
        raw = await self._get(self.latest_path)
        if not raw.ok:
            return AdapterResult(
                self.watcher,
                raw.fetched_at,
                [],
                raw,
                errors=[raw.error or f"HTTP {raw.status_code}"],
            )
        try:
            signals = self.parse(raw.body, raw.fetched_at, self.ttl_seconds)
        except Exception as exc:  # noqa: BLE001 — malformed/unexpected body
            return AdapterResult(
                self.watcher, raw.fetched_at, [], raw, errors=[f"parse error: {exc}"]
            )

        # Reject anything older than max_age (never reuse stale-beyond-policy data).
        fresh: list[NormalizedSignal] = []
        dropped = 0
        for s in signals:
            if s.data_age_seconds(raw.fetched_at) > self.max_age_seconds:
                dropped += 1
            else:
                fresh.append(s)
        errors = [] if fresh else ["all signals older than max_age_seconds"]
        return AdapterResult(
            self.watcher, raw.fetched_at, fresh, raw, errors=errors, dropped_stale=dropped
        )

    async def health(self) -> dict[str, Any]:
        raw = await self._get(self.health_path)
        return {
            "watcher": self.watcher.value,
            "ok": raw.ok,
            "status_code": raw.status_code,
            "error": raw.error,
        }
