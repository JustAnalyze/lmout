from pathlib import Path

from platformdirs import user_data_dir, user_log_dir


def get_project_root() -> Path | None:
    """Returns the project root if running from source, else None."""
    potential_root = Path(__file__).resolve().parent.parent.parent.parent
    if (potential_root / "pyproject.toml").exists():
        return potential_root
    return None


def get_default_data_dir() -> Path:
    """Returns the default data directory (dev folder or XDG)."""
    root = get_project_root()
    if root:
        return root / "outputs"
    return Path(user_data_dir(appname="lock_me_out"))


def get_default_log_dir() -> Path:
    """Returns the default log directory (dev folder or XDG)."""
    root = get_project_root()
    if root:
        return root / "outputs"
    return Path(user_log_dir(appname="lock_me_out"))
