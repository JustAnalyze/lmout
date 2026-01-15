import json
from pathlib import Path

from platformdirs import user_data_dir, user_log_dir
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def get_project_root() -> Path:
    """Returns the project root if running from source, else None."""
    # settings.py is at <root>/src/lock_me_out/settings.py
    potential_root = Path(__file__).resolve().parent.parent.parent
    if (potential_root / "pyproject.toml").exists():
        return potential_root
    return None


def get_default_data_dir() -> Path:
    root = get_project_root()
    if root:
        return root / "outputs"
    return Path(user_data_dir(appname="lock_me_out"))


def get_default_log_dir() -> Path:
    root = get_project_root()
    if root:
        return root / "outputs"
    return Path(user_log_dir(appname="lock_me_out"))


class Settings(BaseSettings):
    app_name: str = "lock_me_out"

    # MASTER SWITCH: Explicitly handle the debug flag from your .env
    debug: bool = Field(default=False, description="Master toggle for verbose logging")

    # Paths
    # If project root / pyproject.toml exists, we are in dev mode
    data_dir: Path = Field(default_factory=get_default_data_dir)
    log_dir: Path = Field(default_factory=get_default_log_dir)
    state_file: Path = Field(
        default_factory=lambda: get_default_data_dir() / "state.json"
    )

    # Icon path: Resolve relative to this file's directory (inside the package)
    icon_path: str = str(Path(__file__).resolve().parent / "resources" / "icon.png")

    # Configuration
    notify_lead_minutes: int = 5
    notify_summary: str = "Lockout in {minutes} minutes"
    notify_body: str = "A scheduled lockout will start at {start_time}."

    # App Blocking
    blocked_apps: list[str] = ["antigravity", "nvim"]

    # Settings from .env take priority
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def save(self):
        """Saves current settings to a config.json in data_dir."""
        config_path = self.data_dir / "config.json"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        # Exclude internal paths/logic fields if necessary, or just dump all
        data = self.model_dump(mode="json")
        with open(config_path, "w") as f:
            json.dump(data, f, indent=4)


def load_settings() -> Settings:
    """Loads settings, merging with config.json if it exists."""
    # First get a default instance to find the data_dir
    initial = Settings()
    config_path = initial.data_dir / "config.json"

    if config_path.exists():
        try:
            with open(config_path) as f:
                config_data = json.load(f)
            # Create a new Settings object merging the JSON data
            return Settings(**config_data)
        except Exception:
            return initial
    return initial


settings = load_settings()
