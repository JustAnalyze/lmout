import json
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from lock_me_out.utils.paths import get_default_data_dir, get_default_log_dir


class Settings(BaseSettings):
    """Application-wide settings managed via .env and config.json."""

    app_name: str = "lock_me_out"
    debug: bool = Field(default=False, description="Master toggle for verbose logging")

    # Paths
    data_dir: Path = Field(default_factory=get_default_data_dir)
    log_dir: Path = Field(default_factory=get_default_log_dir)

    def model_post_init(self, __context):
        # Ensure paths are absolute
        self.data_dir = self.data_dir.resolve()
        self.log_dir = self.log_dir.resolve()

    @property
    def state_file(self) -> Path:
        return self.data_dir / "state.json"

    @property
    def command_file(self) -> Path:
        return self.data_dir / "command.json"

    @property
    def icon_path(self) -> str:
        return str(Path(__file__).resolve().parent / "resources" / "icon.png")

    # Configuration
    notify_lead_minutes: int = 5
    notify_summary: str = "Lockout in {minutes} minutes"
    notify_body: str = "A scheduled lockout will start at {start_time}."

    # App Blocking
    blocked_apps: list[str] = ["antigravity", "nvim"]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def save(self):
        """Saves current settings to config.json in data_dir."""
        config_path = self.data_dir / "config.json"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        data = self.model_dump(mode="json")
        with open(config_path, "w") as f:
            json.dump(data, f, indent=4)



_last_settings_mtime: float | None = None
_cached_settings: Settings | None = None


def load_settings() -> Settings:
    """Loads settings, merging with config.json if it exists."""
    global _last_settings_mtime, _cached_settings

    initial = Settings()
    config_path = initial.data_dir / "config.json"

    if not config_path.exists():
        _last_settings_mtime = None
        _cached_settings = initial
        return initial

    current_mtime = config_path.stat().st_mtime
    if _last_settings_mtime == current_mtime and _cached_settings is not None:
        return _cached_settings

    try:
        with open(config_path) as f:
            config_data = json.load(f)
        _cached_settings = Settings(**initial.model_dump(), **config_data)
        _last_settings_mtime = current_mtime
        return _cached_settings
    except Exception:
        _cached_settings = initial
        return initial


# The single source of truth for the app
settings = load_settings()
