"""Global kill switch (build spec §9). DB/file-persisted state is authoritative — it
survives restarts and, once engaged, requires an explicit clear. Engaging blocks new
orders and exposure-increasing amendments (enforced by the Risk Engine's KILL_SWITCH
check and the execution orchestrator).
"""

from __future__ import annotations

import json
from pathlib import Path

from autopilot.domain.execution.schemas import KillSwitchState
from autopilot.domain.time import now_utc


class KillSwitch:
    """File-backed kill switch. (DB-backed store can drop in behind the same API.)"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def state(self) -> KillSwitchState:
        if not self.path.exists():
            return KillSwitchState()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return KillSwitchState(**raw)
        except Exception:  # noqa: BLE001 — a corrupt file must fail SAFE (engaged)
            return KillSwitchState(
                engaged=True, reason="kill-switch state file unreadable", source="failsafe"
            )

    def engage(self, reason: str, source: str) -> KillSwitchState:
        st = KillSwitchState(engaged=True, reason=reason, source=source, since=now_utc())
        self._write(st)
        return st

    def clear(self, source: str) -> KillSwitchState:
        st = KillSwitchState(
            engaged=False, reason=f"cleared by {source}", source=source, since=now_utc()
        )
        self._write(st)
        return st

    def _write(self, st: KillSwitchState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(st.model_dump_json(indent=2), encoding="utf-8")
