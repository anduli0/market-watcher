"""Best-effort news collector: pulls each watcher's news/brief endpoint and extracts a
couple of short headline/summary strings for the analyst report's 뉴스 흐름 section.
Fully defensive — any failure for a watcher is skipped (never raises, never fabricates).
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

_KEYS = ("headline", "market_read", "market_view", "summary", "title", "lead")
_MAXLEN = 180

# (label, news/brief endpoint) per watcher base url key.
_ENDPOINTS = [
    ("Fed", "fed_watcher_base_url", "/api/briefings/latest"),
    ("환율", "krw_watcher_base_url", "/api/briefing/latest"),
    ("국장", "kospi_watcher_base_url", "/api/v1/news/brief"),
    ("미장", "us_watcher_base_url", "/api/v1/briefings/latest"),
]


def _extract(obj: Any, out: list[str], depth: int = 0) -> None:
    if len(out) >= 2 or depth > 3:
        return
    if isinstance(obj, dict):
        for key in _KEYS:
            val = obj.get(key)
            if isinstance(val, str) and val.strip():
                text = val.strip().replace("\n", " ")
                if text not in out:
                    out.append(text[:_MAXLEN])
                if len(out) >= 2:
                    return
        for v in obj.values():
            _extract(v, out, depth + 1)
    elif isinstance(obj, list):
        for v in obj[:5]:
            _extract(v, out, depth + 1)


async def _one(client: httpx.AsyncClient, label: str, url: str) -> list[tuple[str, str]]:
    try:
        resp = await client.get(url)
        if resp.status_code != 200:
            return []
        found: list[str] = []
        _extract(resp.json(), found)
        return [(label, t) for t in found]
    except Exception:  # noqa: BLE001 — news is decorative; never break the pipeline
        return []


async def collect_news(base_urls: dict[str, str]) -> list[tuple[str, str]]:
    async with httpx.AsyncClient(timeout=4.0) as client:
        tasks = [
            _one(client, label, base_urls[attr].rstrip("/") + path)
            for label, attr, path in _ENDPOINTS
            if attr in base_urls
        ]
        results = await asyncio.gather(*tasks)
    return [item for sub in results for item in sub]
