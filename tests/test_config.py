"""Settings load tokens from secrets/.env, not only the root .env."""
from pathlib import Path

from app.config import Settings


def test_settings_env_files_include_gitignored_secrets_env():
    files = Settings.model_config["env_file"]
    paths = [Path(f) for f in files]
    assert any(p.name == ".env" and p.parent.name != "secrets" for p in paths)
    assert any(p.name == ".env" and p.parent.name == "secrets" for p in paths)
