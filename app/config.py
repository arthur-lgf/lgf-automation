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


def get_settings() -> Settings:
    return Settings()
