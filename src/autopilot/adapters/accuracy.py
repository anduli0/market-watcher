"""Collect each watcher's self-reported out-of-sample accuracy (hit rate) so the Meta-CIO
can weight better-performing watchers more (predictive-power lever). Read-only, defensive,
retried. Returns a hit-rate in [0,1] per watcher (absent if unavailable).

Extraction is EXPLICIT per watcher (pinned to each accuracy endpoint's real shape),
with a hardened generic scan only as a last resort. The old generic-only scan had two
real precision bugs: it picked the US watcher's noisiest 1-day hit rate (0.46) instead
of the horizon the platform actually consumes (5/20-day, 0.59-0.75), and a KOSPI field
like ``window_days`` could be mistaken for a rate via the "win" keyword.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from autopilot.domain.enums import Watcher


def _rate(v: Any) -> float | None:
    """Coerce a plausible hit-rate to [0,1] (percent inputs normalized)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    r = float(v)
    if 0.0 <= r <= 1.0:
        return r
    if 1.0 < r <= 100.0:
        return r / 100.0
    return None


def _extract_fed(d: dict[str, Any]) -> float | None:
    """FED /api/backtest/skill — mean sign hit-rate of the headline (excl-ZLB) block."""
    block = d.get("headline_excl_zlb")
    if not isinstance(block, dict):
        return None
    vals = [
        r
        for v in block.values()
        if isinstance(v, dict)
        for r in (_rate(v.get("hit_rate")),)
        if r is not None
    ]
    return sum(vals) / len(vals) if vals else None


def _extract_krw(d: dict[str, Any]) -> float | None:
    """KRW /api/accuracy — directional hit rate of the best-sampled horizon."""
    horizons = d.get("forecast", {}).get("horizons") if isinstance(d.get("forecast"), dict) else {}
    best: float | None = None
    best_n = 0
    if isinstance(horizons, dict):
        for v in horizons.values():
            if not isinstance(v, dict):
                continue
            n = v.get("samples")
            r = _rate(v.get("directional_hit_rate"))
            if isinstance(n, int) and n > best_n and r is not None:
                best, best_n = r, n
    return best


def _extract_kospi(d: dict[str, Any]) -> float | None:
    """KOSPI /api/v1/accuracy/track — the summary score.hit_rate."""
    score = d.get("score")
    if isinstance(score, dict):
        return _rate(score.get("hit_rate"))
    return None


def _extract_us(d: dict[str, Any]) -> float | None:
    """US /api/v1/accuracy — live hit-rate at horizons >= 5 days (n >= 30), else the
    20-day backtest. The 1-day horizon is intentionally ignored: the platform consumes
    multi-day signals, and 1-day direction is the noisiest series the endpoint offers."""
    live = d.get("live_outcomes", {})
    by_h = live.get("by_horizon", {}) if isinstance(live, dict) else {}
    best: float | None = None
    best_n = 0
    if isinstance(by_h, dict):
        for k, v in by_h.items():
            try:
                horizon_days = int(k)
            except (TypeError, ValueError):
                continue
            if horizon_days < 5 or not isinstance(v, dict):
                continue
            n = v.get("n")
            r = _rate(v.get("hit_rate"))
            if isinstance(n, int) and n >= 30 and n > best_n and r is not None:
                best, best_n = r, n
    if best is not None:
        return best
    backtest = d.get("backtest", {})
    bt_h = backtest.get("by_horizon", {}) if isinstance(backtest, dict) else {}
    if isinstance(bt_h, dict):
        for key in ("20", "60", "5"):
            v = bt_h.get(key)
            if isinstance(v, dict):
                r = _rate(v.get("long_hit_rate")) or _rate(v.get("hit_rate"))
                if r is not None:
                    return r
    return None


_HINT = ("hit", "accuracy", "direction", "win")
# Keys that contain a hint substring but are structurally NOT rates.
_NOT_RATE = ("window", "day", "sample", "count", "num", "size", "horizon")


def _is_rate_key(key: str) -> bool:
    kl = key.lower()
    if kl.startswith("n_") or any(t in kl for t in _NOT_RATE):
        return False  # counts/sizes (e.g. window_days, n_hits), never rates
    return any(t in kl for t in _HINT)


def _find_rate(obj: Any, depth: int = 0) -> float | None:
    """Last-resort generic scan: first plausible hit-rate under an accuracy-ish key."""
    if depth > 5:
        return None
    if isinstance(obj, dict):
        for k, v in obj.items():
            if _is_rate_key(str(k)) and (r := _rate(v)) is not None:
                return r
        for v in obj.values():
            sub = _find_rate(v, depth + 1)
            if sub is not None:
                return sub
    elif isinstance(obj, list):
        for v in obj[:8]:
            sub = _find_rate(v, depth + 1)
            if sub is not None:
                return sub
    return None


def extract_rate(watcher: Watcher, payload: Any) -> float | None:
    if not isinstance(payload, dict):
        return None
    explicit = {
        Watcher.FED_WATCHER: _extract_fed,
        Watcher.KRW_WATCHER: _extract_krw,
        Watcher.KOSPI_WATCHER: _extract_kospi,
        Watcher.US_WATCHER: _extract_us,
    }[watcher](payload)
    if explicit is not None:
        return explicit
    return _find_rate(payload)


_SPEC: dict[Watcher, tuple[str, str]] = {
    Watcher.FED_WATCHER: ("fed_watcher_base_url", "/api/backtest/skill"),
    Watcher.KRW_WATCHER: ("krw_watcher_base_url", "/api/accuracy"),
    Watcher.KOSPI_WATCHER: ("kospi_watcher_base_url", "/api/v1/accuracy/track"),
    Watcher.US_WATCHER: ("us_watcher_base_url", "/api/v1/accuracy"),
}


async def _one(
    client: httpx.AsyncClient, watcher: Watcher, base_urls: dict[str, str]
) -> tuple[Watcher, float | None]:
    attr, path = _SPEC[watcher]
    base = base_urls.get(attr, "").rstrip("/")
    if not base:
        return watcher, None
    for attempt in range(2):
        try:
            r = await client.get(base + path)
            if r.status_code == 200:
                return watcher, extract_rate(watcher, r.json())
            return watcher, None
        except Exception:  # noqa: BLE001 — best-effort; retry once
            if attempt == 0:
                await asyncio.sleep(0.4)
    return watcher, None


async def collect_accuracy(base_urls: dict[str, str]) -> dict[Watcher, float]:
    async with httpx.AsyncClient(timeout=6.0) as client:
        results = await asyncio.gather(*(_one(client, w, base_urls) for w in _SPEC))
    return {w: r for w, r in results if r is not None}
