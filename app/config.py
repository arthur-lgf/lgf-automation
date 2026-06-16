from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    google_application_credentials: Optional[Path] = Field(
        default=None,
        alias="GOOGLE_APPLICATION_CREDENTIALS",
    )

    slack_bot_token: Optional[str] = Field(default=None, alias="SLACK_BOT_TOKEN")
    slack_channel_id: Optional[str] = Field(default=None, alias="SLACK_CHANNEL_ID")

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
    # Channel the report is posted to (the LGF bot must be a member). Falls
    # back to SLACK_CHANNEL_ID when unset.
    approvals_channel_id: Optional[str] = Field(
        default=None, alias="APPROVALS_CHANNEL_ID"
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


def get_settings() -> Settings:
    return Settings()
