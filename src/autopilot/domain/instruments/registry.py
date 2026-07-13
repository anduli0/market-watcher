"""Approved instrument registry loader (config/instruments.yml)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from autopilot.domain.instruments.schemas import Instrument


class InstrumentRegistry:
    def __init__(self, instruments: list[Instrument]) -> None:
        self._by_ticker: dict[str, Instrument] = {i.ticker: i for i in instruments}
        self._by_exposure: dict[str, list[Instrument]] = {}
        for i in instruments:
            self._by_exposure.setdefault(i.exposure, []).append(i)

    @classmethod
    def from_yaml(cls, path: str | Path) -> InstrumentRegistry:
        data: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        rows: list[dict[str, Any]] = data.get("instruments", [])
        return cls([Instrument(**row) for row in rows])

    def all(self) -> list[Instrument]:
        return list(self._by_ticker.values())

    def get(self, ticker: str) -> Instrument | None:
        return self._by_ticker.get(ticker)

    def for_exposure(self, exposure: str) -> list[Instrument]:
        return list(self._by_exposure.get(exposure, []))

    def exposures(self) -> set[str]:
        return set(self._by_exposure)
