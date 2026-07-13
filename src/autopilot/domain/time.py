"""Time discipline: timezone-aware everywhere, stored UTC, displayed KST.
Naive datetimes are rejected at domain boundaries (mirrors kospi-watcher ADR-009).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9), name="Asia/Seoul")


def now_utc() -> datetime:
    """Current time, timezone-aware, in UTC."""
    return datetime.now(UTC)


def ensure_aware_utc(dt: datetime) -> datetime:
    """Return ``dt`` as an aware UTC datetime, rejecting naive input."""
    if dt.tzinfo is None:
        raise ValueError("naive datetime rejected at domain boundary; attach a tzinfo")
    return dt.astimezone(UTC)


def assume_utc(dt: datetime) -> datetime:
    """Attach UTC to a *known-UTC-but-naive* timestamp (e.g. a watcher that
    serializes UTC without an offset). Use ONLY where the source is documented to
    be UTC; never as a blanket coercion."""
    if dt.tzinfo is not None:
        return dt.astimezone(UTC)
    return dt.replace(tzinfo=UTC)


def to_kst(dt: datetime) -> datetime:
    """Convert an aware datetime to KST for display."""
    return ensure_aware_utc(dt).astimezone(KST)


def parse_iso_utc(value: str, *, naive_is_utc: bool = True) -> datetime:
    """Parse an ISO-8601 string to aware UTC. If the string is naive and
    ``naive_is_utc`` is True, assume UTC (documented per-source)."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        if not naive_is_utc:
            raise ValueError(f"naive timestamp not allowed: {value!r}")
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
