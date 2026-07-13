"""Settings (pydantic-settings). Mandated safe defaults: READ_ONLY, live off.
Live arming requires multiple independent gates (RISK_POLICY §4)."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from autopilot.domain.enums import AppMode

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"), extra="ignore", case_sensitive=False
    )

    app_mode: AppMode = AppMode.READ_ONLY
    live_trading_enabled: bool = False
    auto_execution_enabled: bool = False

    fed_watcher_base_url: str = "http://127.0.0.1:8000"
    krw_watcher_base_url: str = "http://127.0.0.1:8010"
    kospi_watcher_base_url: str = "http://127.0.0.1:18080"
    us_watcher_base_url: str = "http://127.0.0.1:8088"

    admin_api_key: str = ""
    tz_display: str = "Asia/Seoul"
    pipeline_cache_seconds: int = 60

    # AI 수석 브리프 — headless `claude -p` via the operator's Claude subscription,
    # invoked BY the web server (auto cadence + dashboard button). Auth = run
    # `claude setup-token` once (or save the token to data/claude_oauth_token.txt).
    # Caps below bound subscription-token spend; unchanged inputs are never re-billed.
    llm_enabled: bool = True
    llm_model: str = "claude-sonnet-5"
    llm_timeout_seconds: int = 420
    llm_auto_minutes: int = 360  # server-side auto refresh cadence
    llm_morning_hour: int = 8  # KST daily anchor; missed -> catch-up ASAP; <0 disables
    llm_daily_cap: int = 8  # max generations per KST day
    llm_manual_min_minutes: int = 10  # min spacing between attempts

    # Bank of Korea rate view for the real-estate section (operator-set, since the KOSPI
    # watcher may lack BOK headlines). hawkish | neutral | dovish. 2026-06 operator input:
    # BOK governor guided >= 2 hikes this year -> hawkish. Korean RE follows BOK (not Fed).
    korea_rate_stance: str = "hawkish"
    korea_expected_hikes: int = 2

    @property
    def config_dir(self) -> Path:
        return ROOT / "config"

    @property
    def data_dir(self) -> Path:
        return ROOT / "data"

    @property
    def live_armed(self) -> bool:
        """A live order may be SENT only when ALL gates hold (and even then the live
        path is not implemented — see KIWOOM_INTEGRATION). A single flag is never
        sufficient."""
        return (
            self.app_mode in (AppMode.BOUNDED_LIVE, AppMode.FULL_AUTOMATION)
            and self.live_trading_enabled
            and self.auto_execution_enabled
        )
