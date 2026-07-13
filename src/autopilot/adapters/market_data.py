"""Keyless daily-close history for the 7 allocation assets (Yahoo chart API).

Used ONLY to score the platform's own past recommendations against realized
returns (track record) — never to fabricate a signal. Defensive: any failure
returns partial data and the scorer simply leaves those days pending.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from autopilot.domain.enums import AssetClass

# Yahoo proxy per asset. CASH is the KRW numeraire (0% daily return by definition).
# USD-quoted assets are converted to a KRW view by the scorer via USDKRW (KRW=X).
PROXY: dict[AssetClass, str] = {
    AssetClass.USD: "KRW=X",  # USD value in KRW terms == USDKRW itself
    AssetClass.US_TREASURY: "IEF",
    AssetClass.US_EQUITY: "^GSPC",
    AssetClass.KOREA_EQUITY: "^KS11",
    AssetClass.BITCOIN: "BTC-USD",
    AssetClass.GOLD: "GLD",
}

_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; market-watcher-track/1.0)"}


def parse_chart(payload: Any) -> list[tuple[str, float]]:
    """Yahoo chart JSON -> sorted [(YYYY-MM-DD, close), ...]. Pure, testable."""
    try:
        result = payload["chart"]["result"][0]
        stamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError):
        return []
    from datetime import UTC, datetime

    out: dict[str, float] = {}
    for ts, close in zip(stamps, closes, strict=False):
        if close is None or not isinstance(close, (int, float)):
            continue
        day = datetime.fromtimestamp(int(ts), tz=UTC).date().isoformat()
        out[day] = float(close)  # last bar of the day wins
    return sorted(out.items())


async def _one(
    client: httpx.AsyncClient, asset: AssetClass, symbol: str, range_: str
) -> tuple[AssetClass, list[tuple[str, float]]]:
    for attempt in range(2):
        try:
            r = await client.get(
                _URL.format(symbol=symbol),
                params={"range": range_, "interval": "1d"},
                headers=_HEADERS,
            )
            if r.status_code == 200:
                return asset, parse_chart(r.json())
            return asset, []
        except Exception:  # noqa: BLE001 — best-effort; retry once
            if attempt == 0:
                await asyncio.sleep(0.4)
    return asset, []


async def fetch_asset_history(range_: str = "3mo") -> dict[str, list[tuple[str, float]]]:
    """Daily closes per asset value-key (e.g. "US_EQUITY"). Missing assets omitted."""
    async with httpx.AsyncClient(timeout=8.0) as client:
        results = await asyncio.gather(
            *(_one(client, a, s, range_) for a, s in PROXY.items())
        )
    return {a.value: series for a, series in results if series}
