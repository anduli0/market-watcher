"""Delegate agents: MARKET WATCHER 'dispatches' an agent to each watcher and collects
DEEP intel — not just the headline forecast but the watcher's own internal agent/desk
outputs and briefings. Read-only and fully defensive (a watcher being slow/down just
yields an empty report; the watcher process is never modified). Feeds the orchestration.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from autopilot.domain.enums import SignalDirection, Watcher
from autopilot.domain.orchestration.schemas import WatcherIntel
from autopilot.domain.signals.schemas import NormalizedSignal

_KEYS = (
    "summary",
    "headline",
    "narrative",
    "reasoning",
    "brief",
    "market_read",
    "diagnosis_ko",
    "title",
    "rationale",
    "lean",
)

# watcher -> (label, settings attr, deep-intel endpoints, signal target)
# Korean-first endpoints so the collected intel notes come back in Korean.
_SPEC: dict[Watcher, tuple[str, str, tuple[str, ...], str]] = {
    Watcher.FED_WATCHER: (
        "미 연준·금리",
        "fed_watcher_base_url",
        ("/api/forecast/report?lang=ko", "/api/briefings/latest?lang=ko"),
        "US_POLICY_RATE_PATH",
    ),
    Watcher.KRW_WATCHER: (
        "원/달러 환율",
        "krw_watcher_base_url",
        ("/api/briefing/latest", "/api/hierarchy"),
        "USD_KRW",
    ),
    Watcher.KOSPI_WATCHER: (
        "한국 증시(국장)",
        "kospi_watcher_base_url",
        ("/api/v1/brief", "/api/v1/agents/org"),
        "KOSPI200",
    ),
    Watcher.US_WATCHER: (
        "미국 증시(미장)",
        "us_watcher_base_url",
        ("/api/v1/market/regime", "/api/v1/briefings/latest"),
        "US_EQUITY",
    ),
}

_LEAN = {
    Watcher.FED_WATCHER: {1: "금리 상방(매파)", -1: "금리 하방(완화)", 0: "동결·중립"},
    Watcher.KRW_WATCHER: {1: "원화 약세·달러 강세", -1: "원화 강세", 0: "환율 중립"},
    Watcher.KOSPI_WATCHER: {1: "국장 강세", -1: "국장 약세", 0: "국장 중립"},
    Watcher.US_WATCHER: {1: "미장 강세", -1: "미장 약세", 0: "미장 혼조"},
}


def _has_hangul(s: str) -> bool:
    return any("가" <= c <= "힣" for c in s)


def _extract(obj: Any, out: list[str], depth: int = 0) -> None:
    if len(out) >= 4 or depth > 4:
        return
    if isinstance(obj, dict):
        for k in _KEYS:
            v = obj.get(k)
            # Korean-only: keep notes that contain Hangul (skip English agent text).
            if isinstance(v, str) and len(v.strip()) > 10 and _has_hangul(v):
                t = v.strip().replace("\n", " ")
                if t not in out:
                    out.append(t[:160])
                if len(out) >= 4:
                    return
        for v in obj.values():
            _extract(v, out, depth + 1)
    elif isinstance(obj, list):
        for v in obj[:6]:
            _extract(v, out, depth + 1)


def _lean(watcher: Watcher, target: str, signals: list[NormalizedSignal]) -> tuple[bool, str]:
    sigs = [s for s in signals if s.target == target]
    if not sigs:
        return False, "신호 없음(워처 미가용/만료)"
    net = 0.0
    for s in sigs:
        d = {SignalDirection.UP: 1.0, SignalDirection.DOWN: -1.0}.get(s.direction, 0.0)
        net += d * s.confidence
    sign = 1 if net > 0.05 else -1 if net < -0.05 else 0
    return True, _LEAN[watcher][sign]


async def _one(
    client: httpx.AsyncClient,
    watcher: Watcher,
    base_urls: dict[str, str],
    signals: list[NormalizedSignal],
) -> WatcherIntel:
    label, attr, paths, target = _SPEC[watcher]
    present, lean = _lean(watcher, target, signals)
    base = base_urls.get(attr, "").rstrip("/")
    notes: list[str] = []
    hit: list[str] = []
    for path in paths:
        if not base or len(notes) >= 4:
            break
        for attempt in range(2):
            try:
                r = await client.get(base + path)
                if r.status_code == 200:
                    hit.append(path)
                    _extract(r.json(), notes)
                break
            except Exception:  # noqa: BLE001 — best-effort; retry once then move on
                if attempt == 0:
                    await asyncio.sleep(0.4)
                    continue
                break
    return WatcherIntel(
        watcher=watcher,
        label_ko=label,
        present=present,
        standalone_lean=lean,
        notes=tuple(notes[:4]),
        endpoints=tuple(hit),
    )


async def collect_intel(
    base_urls: dict[str, str], signals: list[NormalizedSignal]
) -> list[WatcherIntel]:
    async with httpx.AsyncClient(timeout=8.0) as client:
        return list(await asyncio.gather(*(_one(client, w, base_urls, signals) for w in _SPEC)))
