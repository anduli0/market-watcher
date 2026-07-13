"""Persistent, simplified archive of the daily US real-estate picks (impure I/O — used
by the pipeline, not the pure domain). Appends one entry per KST day, idempotently. Each
pick keeps the region + a brief reason. Old {regions:[...]} files are read backward-compat.
"""

from __future__ import annotations

import json
from pathlib import Path

from autopilot.domain.realestate.schemas import ArchiveEntry, ArchivePick


def update_and_load(
    path: Path, date: str, picks: list[tuple[str, str]], *, keep: int = 60, recent: int = 12
) -> list[ArchiveEntry]:
    data: list[dict[str, object]] = []
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                data = [e for e in loaded if isinstance(e, dict)]
        except Exception:  # noqa: BLE001 — corrupt archive starts fresh
            data = []
    new_picks = [{"region": r, "reason": why} for r, why in picks]
    existing = next((e for e in data if e.get("date") == date), None)
    changed = False
    if existing is None:
        data.append({"date": date, "picks": new_picks})
        data = data[-keep:]
        changed = True
    elif not existing.get("picks") and new_picks:
        # upgrade an old {regions:[...]} same-day entry to include reasons
        existing["picks"] = new_picks
        existing.pop("regions", None)
        changed = True
    if changed:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001 — archiving must never break the pipeline
            pass

    out: list[ArchiveEntry] = []
    for e in reversed(data[-recent:]):
        raw = e.get("picks")
        if isinstance(raw, list):
            ps = [
                ArchivePick(region=str(p.get("region", "")), reason=str(p.get("reason", "")))
                for p in raw
                if isinstance(p, dict)
            ]
        else:  # backward-compat with old {"regions": [...]} entries
            regs = e.get("regions", [])
            ps = [ArchivePick(region=str(r)) for r in regs] if isinstance(regs, list) else []
        out.append(ArchiveEntry(date=str(e.get("date", "")), picks=tuple(ps)))
    return out
