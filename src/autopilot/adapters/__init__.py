"""WATCHER adapters — the only components that talk to the watcher HTTP endpoints."""

from autopilot.adapters.base import AdapterResult, RawResponse, WatcherAdapter
from autopilot.adapters.fed import FedWatcherAdapter
from autopilot.adapters.kospi import KospiWatcherAdapter
from autopilot.adapters.krw import KrwWatcherAdapter
from autopilot.adapters.us import UsStockWatcherAdapter
from autopilot.domain.enums import Watcher

ADAPTER_TYPES: dict[Watcher, type[WatcherAdapter]] = {
    Watcher.FED_WATCHER: FedWatcherAdapter,
    Watcher.KRW_WATCHER: KrwWatcherAdapter,
    Watcher.KOSPI_WATCHER: KospiWatcherAdapter,
    Watcher.US_WATCHER: UsStockWatcherAdapter,
}

__all__ = [
    "ADAPTER_TYPES",
    "AdapterResult",
    "FedWatcherAdapter",
    "KospiWatcherAdapter",
    "KrwWatcherAdapter",
    "RawResponse",
    "UsStockWatcherAdapter",
    "WatcherAdapter",
]
