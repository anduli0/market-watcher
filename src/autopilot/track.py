"""TrackService — persistence + scheduling glue for the own-track-record loop.

record(): upsert today's recommendation (latest state of the KST day wins).
refresh_scores(): fetch realized closes (keyless Yahoo, 6h-cached) -> score all
recorded predictions -> persist. calibration(): the persisted realized-vs-stated
stats the pipeline feeds into `calibrate_confidence` (bounded, sample-gated).
Everything is defensive: a failure leaves the last persisted state untouched.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from autopilot.adapters.market_data import fetch_asset_history
from autopilot.config import Settings
from autopilot.domain.time import now_utc, to_kst
from autopilot.domain.track.engine import score_predictions
from autopilot.domain.track.schemas import TrackPrediction

if TYPE_CHECKING:
    from autopilot.pipeline import PipelineResult

SCORE_TTL_SECONDS = 6 * 3600


class TrackService:
    def __init__(
        self,
        settings: Settings,
        *,
        predictions_path: Path | None = None,
        scores_path: Path | None = None,
    ) -> None:
        self.settings = settings
        self._pred_path = predictions_path or (settings.data_dir / "track_predictions.json")
        self._score_path = scores_path or (settings.data_dir / "track_scores.json")

    # ── storage ──────────────────────────────────────────────────────────────

    def _read(self, path: Path) -> dict[str, Any]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write(self, path: Path, data: dict[str, Any]) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)

    def predictions(self) -> list[TrackPrediction]:
        raw = self._read(self._pred_path)
        out: list[TrackPrediction] = []
        for v in raw.values():
            try:
                out.append(TrackPrediction.model_validate(v))
            except ValueError:
                continue
        return out

    # ── recording (called from every successful pipeline refresh) ────────────

    def record(self, result: PipelineResult) -> None:
        if result.warming or result.snapshot.coverage <= 0.0:
            return  # never record a placeholder as a prediction
        day = to_kst(result.as_of).date().isoformat()
        row = {
            "date": day,
            "regime": result.regime.primary_regime.value,
            "secondary": (
                result.regime.secondary_regime.value if result.regime.secondary_regime else None
            ),
            "confidence": round(result.regime.confidence, 4),
            "risk_on": round(result.cio.risk_on_score, 4),
            "coverage": round(result.snapshot.coverage, 4),
            "weights": {a.asset.value: a.weight for a in result.portfolio.allocations},
            "neutral": {a.asset.value: a.neutral_weight for a in result.portfolio.allocations},
        }
        try:
            store = self._read(self._pred_path)
            store[day] = row  # latest state of the day wins
            self._write(self._pred_path, store)
        except OSError:
            pass  # track record must never break the pipeline

    # ── scoring ──────────────────────────────────────────────────────────────

    def _scores_stale(self) -> bool:
        raw = self._read(self._score_path)
        updated = raw.get("updated_at")
        if not isinstance(updated, str):
            return True
        try:
            age = (now_utc() - datetime.fromisoformat(updated)).total_seconds()
        except ValueError:
            return True
        return age > SCORE_TTL_SECONDS

    async def refresh_scores(self, *, force: bool = False) -> None:
        """Score every recorded prediction against realized returns; persist."""
        if not force and not self._scores_stale():
            return
        preds = self.predictions()
        if not preds:
            return
        try:
            prices = await fetch_asset_history()
        except Exception:  # noqa: BLE001 — network is best-effort
            return
        if not prices:
            return
        scores, summary = score_predictions(preds, prices)
        self._write(
            self._score_path,
            {
                "updated_at": now_utc().isoformat(),
                "summary": summary.model_dump(mode="json"),
                "scores": [s.model_dump(mode="json") for s in scores],
            },
        )

    # ── reads ────────────────────────────────────────────────────────────────

    def report(self) -> dict[str, Any]:
        raw = self._read(self._score_path)
        summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else None
        raw_scores = raw.get("scores")
        scores: list[Any] = raw_scores if isinstance(raw_scores, list) else []
        n_dir = int(summary.get("n_directional", 0)) if summary else 0
        from autopilot.domain.track.engine import MIN_SCORED

        return {
            "summary": summary,
            "scores": scores[-40:],
            "n_predictions_recorded": len(self._read(self._pred_path)),
            "calibration_active": n_dir >= MIN_SCORED,
            "calibration_min_n": MIN_SCORED,
            "updated_at": raw.get("updated_at"),
        }

    def calibration(self) -> dict[str, Any] | None:
        """Realized-vs-stated stats for `calibrate_confidence` (None until scored)."""
        raw = self._read(self._score_path)
        s = raw.get("summary")
        if not isinstance(s, dict):
            return None
        return {
            "hit_rate": s.get("hit_rate"),
            "avg_stated_confidence": s.get("avg_stated_confidence"),
            "n_directional": int(s.get("n_directional", 0)),
        }
