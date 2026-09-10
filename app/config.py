from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(
            _REPO_ROOT / ".env",
            _REPO_ROOT / "secrets" / ".env",
        ),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    google_application_credentials: Optional[Path] = Field(
        default=None,
        alias="GOOGLE_APPLICATION_CREDENTIALS",
    )

    slack_bot_token: Optional[str] = Field(default=None, alias="SLACK_BOT_TOKEN")
    slack_channel_id: Optional[str] = Field(default=None, alias="SLACK_CHANNEL_ID")
    # Dedicated Gold Slack app bot (https://api.slack.com/apps/A0C11GQ6ESE).
    # Falls back to SLACK_BOT_TOKEN when unset.
    gold_slack_bot_token: Optional[str] = Field(
        default=None, alias="GOLD_SLACK_BOT_TOKEN"
    )
    gold_channel_id: str = Field(default="C0ATW4FSK0X", alias="GOLD_CHANNEL_ID")
    # Test-only extra channel C0BFN82DDLN. Leave unset in production.
    gold_extra_channel_id: Optional[str] = Field(
        default=None, alias="GOLD_EXTRA_CHANNEL_ID"
    )

    default_spreadsheet_id: Optional[str] = Field(
        default="12glaANnP2BsQfH_kHfRlzA40JdWAU-PJgDT-56yRV8k",
        alias="DEFAULT_SPREADSHEET_ID",
    )
    default_gid: Optional[int] = Field(default=170384010, alias="DEFAULT_GID")
    default_range: Optional[str] = Field(default="B1:J25", alias="DEFAULT_RANGE")

    viewport_width: int = Field(default=1400, alias="VIEWPORT_WIDTH")
    viewport_height: int = Field(default=900, alias="VIEWPORT_HEIGHT")

    # --- Approvals report (GET /reports/approvals) -------------------------
    # APPTRACK 3.0 workbook, tab "APPS". Defaults so the cron URL stays short.
    approvals_spreadsheet_id: str = Field(
        default="1Tc8x72ys7_oWQnUm03LWa-KHgHMXmX2HGH7gz1-xC_c",
        alias="APPROVALS_SPREADSHEET_ID",
    )
    approvals_gid: int = Field(default=340057391, alias="APPROVALS_GID")
    # Passing the tab name lets fetch_values skip the extra gid->name metadata
    # round-trip. Blank it to fall back to gid resolution.
    approvals_sheet_name: str = Field(default="APPS", alias="APPROVALS_SHEET_NAME")
    approvals_range: str = Field(default="A1:L", alias="APPROVALS_RANGE")
    # Channel the report is posted to (the bot must be a member). Falls
    # back to SLACK_CHANNEL_ID when unset.
    # Test-only channel C0BFN82DDLN. Leave unset in production.
    approvals_channel_id: Optional[str] = Field(
        default=None, alias="APPROVALS_CHANNEL_ID"
    )
    # Optional separate Slack bot for the approvals report (so it doesn't share
    # the snapshot bot). Falls back to SLACK_BOT_TOKEN when unset.
    approvals_slack_bot_token: Optional[str] = Field(
        default=None, alias="APPROVALS_SLACK_BOT_TOKEN"
    )
    report_tz: str = Field(default="America/New_York", alias="REPORT_TZ")
    # 0-based column indices within the A1:L fetch, in the order:
    # date_approved, client, bank, amount, invoice_sent, rep  (=> B,E,G,I,K,L)
    approvals_cols: str = Field(default="1,4,6,8,10,11", alias="APPROVALS_COLS")

    def approvals_cols_map(self) -> dict[str, int]:
        keys = ("date_approved", "client", "bank", "amount", "invoice_sent", "rep")
        tokens = [t.strip() for t in str(self.approvals_cols).split(",") if t.strip()]
        try:
            parts = [int(t) for t in tokens]
        except ValueError as exc:
            raise ValueError(
                "APPROVALS_COLS must be comma-separated integers "
                "(date_approved,client,bank,amount,invoice_sent,rep); "
                f"got {self.approvals_cols!r}"
            ) from exc
        if len(parts) != len(keys):
            raise ValueError(
                f"APPROVALS_COLS must list exactly {len(keys)} integers "
                "(date_approved,client,bank,amount,invoice_sent,rep); "
                f"got {len(parts)} in {self.approvals_cols!r}"
            )
        return dict(zip(keys, parts))

    # --- Approvals Analysis charts (scripts/approvals_analysis.py) ----------
    # Weekly + monthly bar charts aggregated from the APPS tab (same sheet as
    # the tables). Mirrors SALES_ANALYSIS_WEEKLY_WEEKS / _MONTHLY_MONTHS.
    approvals_analysis_weekly_weeks: int = Field(
        default=6, alias="APPROVALS_ANALYSIS_WEEKLY_WEEKS"
    )
    approvals_analysis_monthly_months: int = Field(
        default=5, alias="APPROVALS_ANALYSIS_MONTHLY_MONTHS"
    )

    # --- Sales Analysis charts (scripts/sales_analysis.py) -----------------
    # Weekly + monthly bar charts re-rendered from the Analysis tab of the sales
    # workbook (gid 1867438179). Spreadsheet id reuses DEFAULT_SPREADSHEET_ID.
    sales_analysis_gid: int = Field(default=1867438179, alias="SALES_ANALYSIS_GID")
    # One fetch covering both blocks: weekly in cols B:E, monthly in cols N:Q.
    sales_analysis_range: str = Field(default="A1:Q40", alias="SALES_ANALYSIS_RANGE")
    # Weekly chart shows only the most recent N completed weeks (0 = all).
    sales_analysis_weekly_weeks: int = Field(
        default=5, alias="SALES_ANALYSIS_WEEKLY_WEEKS"
    )
    # Monthly chart shows the most recent N completed months (0 = all), plus the
    # current in-progress month when it has data.
    sales_analysis_monthly_months: int = Field(
        default=5, alias="SALES_ANALYSIS_MONTHLY_MONTHS"
    )
    # Channel the charts post to (defaults to the sales channel SLACK_CHANNEL_ID).
    sales_analysis_channel_id: Optional[str] = Field(
        default=None, alias="SALES_ANALYSIS_CHANNEL_ID"
    )
    # Optional dedicated Slack bot; falls back to SLACK_BOT_TOKEN when unset.
    sales_analysis_slack_bot_token: Optional[str] = Field(
        default=None, alias="SALES_ANALYSIS_SLACK_BOT_TOKEN"
    )
    # When true, the monthly chart's in-progress month is sourced from the Sales
    # Report tab (same workbook, gid 170384010) instead of the Analysis tab's own
    # value. Currently OFF — the chart uses the Analysis tab's figure. Flip to
    # true (or set SALES_REPORT_CURRENT_MONTH_OVERRIDE=1) to re-enable.
    sales_report_current_month_override: bool = Field(
        default=False, alias="SALES_REPORT_CURRENT_MONTH_OVERRIDE"
    )
    sales_report_gid: int = Field(default=170384010, alias="SALES_REPORT_GID")
    sales_report_monthly_range: str = Field(
        default="G1:J50", alias="SALES_REPORT_MONTHLY_RANGE"
    )

    # --- Skool dashboard report (scripts/skool.py) -------------------------
    # Skool session 'auth_token' cookie value, injected into the browser context (Skool exposes no API).
    skool_auth_token: Optional[str] = Field(
        default=None, alias="SKOOL_AUTH_TOKEN"
    )
    # URL of the Skool dashboard (e.g., https://skool.com/dashboard).
    skool_dashboard_url: Optional[str] = Field(
        default=None, alias="SKOOL_DASHBOARD_URL"
    )
    # CSS selector for capturing the dashboard panel (defaults to "body" for
    # spike-friendly dry runs; narrow to dashboard selector once confirmed).
    skool_capture_selector: str = Field(
        default="body", alias="SKOOL_CAPTURE_SELECTOR"
    )
    # Cookie domain for Skool authentication.
    skool_cookie_domain: str = Field(
        default=".skool.com", alias="SKOOL_COOKIE_DOMAIN"
    )
    # Slack channel to post the Skool snapshot to. Falls back to
    # SLACK_CHANNEL_ID when unset.
    skool_channel_id: Optional[str] = Field(
        default=None, alias="SKOOL_CHANNEL_ID"
    )
    # Optional separate Slack bot for the Skool snapshot (so it doesn't share
    # the snapshot bot). Falls back to SLACK_BOT_TOKEN when unset.
    skool_slack_bot_token: Optional[str] = Field(
        default=None, alias="SKOOL_SLACK_BOT_TOKEN"
    )


def get_settings() -> Settings:
    return Settings()
